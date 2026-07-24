from __future__ import annotations

import base64
import json
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path

import numpy as np
import torch

from secure_dfl_platform.codec import average_states, decode_state, encode_state
from secure_dfl_platform.crypto import derive_demo_private_key
from secure_dfl_platform.key_management import write_node_keys
from secure_dfl_platform.masking import apply_mask, generate_mask_for_state, remove_mask
from secure_dfl_platform.protocol import UpdateEnvelope, create_envelope
from secure_dfl_platform.runtime import NodeRuntime
from secure_dfl_platform.training_adapter import (
    numpy_state_to_torch,
    torch_state_to_numpy,
)
from operator_dashboard import is_dashboard_request_authorized
from verify_audit_logs import verify_audit_file


class CodecTests(unittest.TestCase):
    def test_state_round_trip_and_average(self):
        left = OrderedDict([("weight", np.asarray([1.0, 3.0], dtype=np.float32))])
        right = OrderedDict([("weight", np.asarray([3.0, 5.0], dtype=np.float32))])
        restored = decode_state(encode_state(left), 1024 * 1024)
        np.testing.assert_array_equal(restored["weight"], left["weight"])
        averaged = average_states([left, right])
        np.testing.assert_allclose(averaged["weight"], [2.0, 4.0])

    def test_torch_numpy_adapter_round_trip(self):
        model = torch.nn.Linear(3, 2)
        numpy_state = torch_state_to_numpy(model.state_dict())
        restored = numpy_state_to_torch(numpy_state, model.state_dict())

        self.assertEqual(list(restored), list(model.state_dict()))
        for name, tensor in model.state_dict().items():
            self.assertTrue(torch.equal(restored[name], tensor))

    def test_additive_masking_round_trip(self):
        state = OrderedDict([("weight", np.asarray([1.0, 3.0], dtype=np.float32))])
        mask = generate_mask_for_state(state, seed=123)
        masked = apply_mask(state, mask)
        restored = remove_mask(masked, mask)
        np.testing.assert_allclose(restored["weight"], state["weight"], atol=1e-6)


class RuntimeTests(unittest.TestCase):
    def test_signed_exchange_and_finalize(self):
        seed = "test-seed"
        key0 = derive_demo_private_key("node0", seed)
        key1 = derive_demo_private_key("node1", seed)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = NodeRuntime(
                node_id="node0",
                experiment_id="exp",
                peer_ids=["node1"],
                private_key=key0,
                trusted_keys={"node1": key1.public_key()},
                data_dir=Path(tmp),
                max_payload_bytes=1024 * 1024,
            )
            local = OrderedDict([("weight", np.asarray([1.0, 3.0], dtype=np.float32))])
            peer = OrderedDict([("weight", np.asarray([3.0, 5.0], dtype=np.float32))])
            runtime.register_local_payload(1, encode_state(local))
            envelope = create_envelope(
                private_key=key1,
                experiment_id="exp",
                round_number=1,
                sender_id="node1",
                recipient_id="node0",
                payload=encode_state(peer),
            )
            self.assertTrue(runtime.accept_peer_envelope(envelope)["accepted"])
            aggregate_payload, status = runtime.finalize_round(1)
            aggregate = decode_state(aggregate_payload, 1024 * 1024)
            np.testing.assert_allclose(aggregate["weight"], [2.0, 4.0])
            self.assertTrue(status["finalized"])
            self.assertTrue((Path(tmp) / "node_audit.jsonl").exists())

    def test_masked_signed_exchange_and_finalize(self):
        seed = "test-seed"
        key0 = derive_demo_private_key("node0", seed)
        key1 = derive_demo_private_key("node1", seed)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = NodeRuntime(
                node_id="node0",
                experiment_id="exp",
                peer_ids=["node1"],
                private_key=key0,
                trusted_keys={"node1": key1.public_key()},
                data_dir=Path(tmp),
                max_payload_bytes=1024 * 1024,
                security_mode="masking",
            )
            local = OrderedDict([("weight", np.asarray([1.0, 3.0], dtype=np.float32))])
            peer = OrderedDict([("weight", np.asarray([3.0, 5.0], dtype=np.float32))])
            runtime.register_local_payload(1, encode_state(local))
            envelope = create_envelope(
                private_key=key1,
                experiment_id="exp",
                round_number=1,
                sender_id="node1",
                recipient_id="node0",
                payload=encode_state(peer),
                security_mode="masking",
                max_payload_bytes=1024 * 1024,
                mask_seed=7,
            )
            self.assertEqual(envelope.security_mode, "masking")
            self.assertGreater(envelope.masking_overhead_bytes, 0)
            self.assertTrue(runtime.accept_peer_envelope(envelope)["accepted"])
            aggregate_payload, status = runtime.finalize_round(1)
            aggregate = decode_state(aggregate_payload, 1024 * 1024)
            np.testing.assert_allclose(aggregate["weight"], [2.0, 4.0])
            self.assertTrue(status["finalized"])
            metrics = runtime.node_status()["metrics"]
            self.assertEqual(metrics["masked_updates_received_total"], 1)
            self.assertGreater(metrics["received_masking_overhead_bytes_total"], 0)

    def test_tampered_mask_in_envelope_is_rejected(self):
        seed = "test-seed"
        key0 = derive_demo_private_key("node0", seed)
        key1 = derive_demo_private_key("node1", seed)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = NodeRuntime(
                node_id="node0",
                experiment_id="exp",
                peer_ids=["node1"],
                private_key=key0,
                trusted_keys={"node1": key1.public_key()},
                data_dir=Path(tmp),
                max_payload_bytes=1024 * 1024,
                security_mode="masking",
            )
            peer = OrderedDict([("weight", np.asarray([3.0, 5.0], dtype=np.float32))])
            envelope = create_envelope(
                private_key=key1,
                experiment_id="exp",
                round_number=1,
                sender_id="node1",
                recipient_id="node0",
                payload=encode_state(peer),
                security_mode="masking",
                max_payload_bytes=1024 * 1024,
                mask_seed=7,
            )
            raw = envelope.to_dict()
            raw["mask_payload_b64"] = raw["mask_payload_b64"][:-4] + "AAAA"
            with self.assertRaisesRegex(ValueError, "invalid Ed25519 signature"):
                runtime.accept_peer_envelope(UpdateEnvelope.from_dict(raw))

    def test_tampered_signature_is_rejected(self):
        seed = "test-seed"
        key0 = derive_demo_private_key("node0", seed)
        key1 = derive_demo_private_key("node1", seed)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = NodeRuntime(
                node_id="node0",
                experiment_id="exp",
                peer_ids=["node1"],
                private_key=key0,
                trusted_keys={"node1": key1.public_key()},
                data_dir=Path(tmp),
                max_payload_bytes=1024 * 1024,
            )
            payload = encode_state(
                OrderedDict([("weight", np.asarray([1.0], dtype=np.float32))])
            )
            envelope = create_envelope(
                private_key=key1,
                experiment_id="exp",
                round_number=1,
                sender_id="node1",
                recipient_id="node0",
                payload=payload,
            )
            raw = envelope.to_dict()
            raw["signature_b64"] = base64.b64encode(b"0" * 64).decode("ascii")
            with self.assertRaisesRegex(ValueError, "invalid Ed25519 signature"):
                runtime.accept_peer_envelope(UpdateEnvelope.from_dict(raw))

    def test_default_requires_all_peers_before_finalize(self):
        seed = "test-seed"
        key0 = derive_demo_private_key("node0", seed)
        key1 = derive_demo_private_key("node1", seed)
        key2 = derive_demo_private_key("node2", seed)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = NodeRuntime(
                node_id="node0",
                experiment_id="exp",
                peer_ids=["node1", "node2"],
                private_key=key0,
                trusted_keys={"node1": key1.public_key(), "node2": key2.public_key()},
                data_dir=Path(tmp),
                max_payload_bytes=1024 * 1024,
            )
            runtime.register_local_payload(
                1,
                encode_state(OrderedDict([("weight", np.asarray([1.0], dtype=np.float32))])),
            )
            envelope = create_envelope(
                private_key=key1,
                experiment_id="exp",
                round_number=1,
                sender_id="node1",
                recipient_id="node0",
                payload=encode_state(
                    OrderedDict([("weight", np.asarray([3.0], dtype=np.float32))])
                ),
            )
            runtime.accept_peer_envelope(envelope)

            self.assertFalse(runtime.round_status(1)["ready"])
            with self.assertRaisesRegex(RuntimeError, "required_peer_updates=2"):
                runtime.finalize_round(1)

    def test_quorum_can_finalize_with_missing_peer(self):
        seed = "test-seed"
        key0 = derive_demo_private_key("node0", seed)
        key1 = derive_demo_private_key("node1", seed)
        key2 = derive_demo_private_key("node2", seed)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = NodeRuntime(
                node_id="node0",
                experiment_id="exp",
                peer_ids=["node1", "node2"],
                private_key=key0,
                trusted_keys={"node1": key1.public_key(), "node2": key2.public_key()},
                data_dir=Path(tmp),
                max_payload_bytes=1024 * 1024,
                min_peer_updates_to_finalize=1,
            )
            runtime.register_local_payload(
                1,
                encode_state(OrderedDict([("weight", np.asarray([1.0], dtype=np.float32))])),
            )
            envelope = create_envelope(
                private_key=key1,
                experiment_id="exp",
                round_number=1,
                sender_id="node1",
                recipient_id="node0",
                payload=encode_state(
                    OrderedDict([("weight", np.asarray([3.0], dtype=np.float32))])
                ),
            )
            runtime.accept_peer_envelope(envelope)

            self.assertTrue(runtime.round_status(1)["partial_ready"])
            aggregate_payload, status = runtime.finalize_round(1)
            aggregate = decode_state(aggregate_payload, 1024 * 1024)
            np.testing.assert_allclose(aggregate["weight"], [2.0])
            self.assertTrue(status["finalized"])
            self.assertTrue(status["partial_ready"])
            self.assertEqual(status["missing_peers"], ["node2"])
            self.assertEqual(runtime.node_status()["metrics"]["partial_finalizations_total"], 1)


class DeploymentWorkflowTests(unittest.TestCase):
    def test_key_generation_and_audit_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_dir = Path(tmp) / "keys"
            metadata = write_node_keys(
                node_ids=["node0", "node1"],
                output_dir=key_dir,
            )
            self.assertTrue((key_dir / "trusted_keys.json").exists())
            self.assertTrue(Path(metadata["node0"]["private_key_file"]).exists())

            key0 = derive_demo_private_key("node0", "audit-test")
            key1 = derive_demo_private_key("node1", "audit-test")
            runtime = NodeRuntime(
                node_id="node0",
                experiment_id="exp",
                peer_ids=["node1"],
                private_key=key0,
                trusted_keys={"node1": key1.public_key()},
                data_dir=Path(tmp) / "node0",
                max_payload_bytes=1024 * 1024,
            )
            runtime.register_local_payload(
                1,
                encode_state(OrderedDict([("weight", np.asarray([1.0], dtype=np.float32))])),
            )

            # The generated key manifest is unrelated to the demo runtime above,
            # so build the matching manifest explicitly for this verification test.
            trusted_path = Path(tmp) / "trusted_keys_for_runtime.json"
            from secure_dfl_platform.crypto import public_key_b64

            trusted_path.write_text(
                json.dumps({"node0": public_key_b64(key0.public_key())}),
                encoding="utf-8",
            )
            result = verify_audit_file(runtime.audit_path, trusted_path)
            self.assertTrue(result["valid"], result["errors"])
            self.assertGreaterEqual(result["records"], 2)

            auto_trust_result = verify_audit_file(runtime.audit_path, None)
            self.assertTrue(auto_trust_result["valid"], auto_trust_result["errors"])
            self.assertEqual(auto_trust_result["trust_source"], "audit_log_node_started")

    def test_dashboard_token_authorization_rules(self):
        self.assertTrue(is_dashboard_request_authorized("", None))
        self.assertTrue(is_dashboard_request_authorized("", "anything"))
        self.assertFalse(is_dashboard_request_authorized("secret", None))
        self.assertFalse(is_dashboard_request_authorized("secret", "wrong"))
        self.assertTrue(is_dashboard_request_authorized("secret", "secret"))


if __name__ == "__main__":
    unittest.main()
