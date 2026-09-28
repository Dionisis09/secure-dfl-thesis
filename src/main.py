"""Command-line runner for the baseline decentralized FL experiment."""

import argparse
import time
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List

import torch
from tqdm import tqdm

from adaptive import compute_target_risk_scores, select_he_targets
from aggregation import average_state_dicts, estimate_model_size_bytes
from client import Client
from config import Config
from data_utils import (
    create_iid_client_loaders,
    create_non_iid_client_loaders,
    get_datasets,
    get_test_loader,
    normalize_dataset_name,
    set_seed,
)
from he_utils import (
    create_ckks_context,
    get_final_layer_param_names,
    homomorphic_average_selected_params_only,
    import_tenseal_or_raise,
    parse_coeff_mod_bits,
    selected_plain_size_bytes,
    selective_he_aggregate_for_target,
)
from metrics import (
    MetricsLogger,
    plot_accuracy,
    plot_communication,
    plot_loss,
    plot_round_time,
)
from masking import (
    apply_mask,
    build_masked_contributions_for_target,
    estimate_masking_overhead_bytes,
    generate_mask_for_state_dict,
    max_state_dict_difference,
    remove_mask,
)
from model import SimpleMLP
from topology import (
    Topology,
    create_fully_connected_topology,
    create_random_topology,
    create_ring_topology,
    create_small_world_topology,
    create_star_topology,
)
from train_utils import evaluate_all_clients


def parse_args() -> argparse.Namespace:
    defaults = Config()
    parser = argparse.ArgumentParser(
        description="Decentralized federated learning experiment runner"
    )
    parser.add_argument("--num_clients", type=int, default=defaults.num_clients)
    parser.add_argument("--num_rounds", type=int, default=defaults.num_rounds)
    parser.add_argument("--local_epochs", type=int, default=defaults.local_epochs)
    parser.add_argument("--batch_size", type=int, default=defaults.batch_size)
    parser.add_argument("--lr", type=float, default=defaults.learning_rate)
    parser.add_argument(
        "--device", choices=["cuda", "cpu"], default=defaults.device
    )
    parser.add_argument(
        "--split_type", choices=["iid", "non_iid"], default=defaults.split_type
    )
    parser.add_argument(
        "--dataset",
        choices=["mnist", "fashion_mnist", "fmnist", "cifar10"],
        default=defaults.dataset,
        help="Dataset used by the DFL experiment",
    )
    parser.add_argument(
        "--topology",
        choices=["ring", "fully_connected", "star", "random", "small_world"],
        default=defaults.topology,
    )
    parser.add_argument(
        "--security_mode",
        choices=[
            "none",
            "masking",
            "pairwise_masking",
            "selective_he",
            "adaptive_hybrid",
        ],
        default=defaults.security_mode,
        help="Protection applied to peer-to-peer model sharing",
    )
    parser.add_argument("--he_scheme", choices=["ckks"], default=defaults.he_scheme)
    parser.add_argument(
        "--he_poly_modulus_degree",
        type=int,
        default=defaults.he_poly_modulus_degree,
    )
    parser.add_argument(
        "--he_scale_bits", type=int, default=defaults.he_scale_bits
    )
    parser.add_argument(
        "--he_coeff_mod_bits", default=defaults.he_coeff_mod_bits
    )
    parser.add_argument(
        "--he_selected_layer",
        choices=["final"],
        default=defaults.he_selected_layer,
    )
    parser.add_argument(
        "--adaptive_policy",
        choices=["topk_risk", "threshold", "periodic"],
        default=defaults.adaptive_policy,
    )
    parser.add_argument(
        "--adaptive_he_target_ratio",
        type=float,
        default=defaults.adaptive_he_target_ratio,
    )
    parser.add_argument(
        "--adaptive_risk_threshold",
        type=float,
        default=defaults.adaptive_risk_threshold,
    )
    parser.add_argument(
        "--adaptive_he_every_n_rounds",
        type=int,
        default=defaults.adaptive_he_every_n_rounds,
    )
    parser.add_argument(
        "--adaptive_min_he_targets",
        type=int,
        default=defaults.adaptive_min_he_targets,
    )
    parser.add_argument(
        "--experiment_name",
        type=str,
        default=defaults.experiment_name,
        help="Name used for the metrics CSV and plot directory",
    )
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument(
        "--enable_blockchain",
        action="store_true",
        help="Enable the optional audit-only blockchain ledger",
    )
    parser.add_argument(
        "--enable_audit",
        action="store_true",
        help="Enable the product-style Ed25519 audit package",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    positive_values = {
        "num_clients": args.num_clients,
        "num_rounds": args.num_rounds,
        "local_epochs": args.local_epochs,
        "batch_size": args.batch_size,
    }
    for name, value in positive_values.items():
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero")
    if args.lr <= 0:
        raise ValueError("lr must be greater than zero")
    if not 0.0 <= args.adaptive_he_target_ratio <= 1.0:
        raise ValueError("adaptive_he_target_ratio must be between 0 and 1")
    if args.adaptive_he_every_n_rounds <= 0:
        raise ValueError("adaptive_he_every_n_rounds must be greater than zero")
    if args.adaptive_min_he_targets < 0:
        raise ValueError("adaptive_min_he_targets cannot be negative")
    if not args.experiment_name.strip():
        raise ValueError("experiment_name cannot be empty")
    if (
        args.experiment_name in {".", ".."}
        or Path(args.experiment_name).name != args.experiment_name
    ):
        raise ValueError("experiment_name must not contain path separators")
    args.dataset = normalize_dataset_name(args.dataset)


def build_topology(name: str, num_clients: int, seed: int) -> Topology:
    if name == "ring":
        return create_ring_topology(num_clients)
    if name == "fully_connected":
        return create_fully_connected_topology(num_clients)
    if name == "star":
        return create_star_topology(num_clients)
    if name == "small_world":
        return create_small_world_topology(num_clients, seed=seed)
    return create_random_topology(num_clients, degree=2, seed=seed)


def resolve_device(requested_device: str) -> str:
    """Use CUDA by default while retaining a safe CPU fallback."""

    if requested_device == "cuda" and not torch.cuda.is_available():
        print("Warning: CUDA is unavailable; falling back to CPU.")
        return "cpu"
    return requested_device


def build_blockchain_configuration(
    args: argparse.Namespace, device: str
) -> Dict[str, object]:
    return {
        "experiment_name": args.experiment_name,
        "security_mode": args.security_mode,
        "seed": args.seed,
        "num_clients": args.num_clients,
        "num_rounds": args.num_rounds,
        "local_epochs": args.local_epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.lr,
        "dataset": args.dataset,
        "topology": args.topology,
        "split_type": args.split_type,
        "device": device,
        "he_scheme": args.he_scheme,
        "he_poly_modulus_degree": args.he_poly_modulus_degree,
        "he_scale_bits": args.he_scale_bits,
        "he_coeff_mod_bits": args.he_coeff_mod_bits,
        "he_selected_layer": args.he_selected_layer,
        "adaptive_policy": args.adaptive_policy,
        "adaptive_he_target_ratio": args.adaptive_he_target_ratio,
        "adaptive_risk_threshold": args.adaptive_risk_threshold,
        "adaptive_he_every_n_rounds": args.adaptive_he_every_n_rounds,
        "adaptive_min_he_targets": args.adaptive_min_he_targets,
    }


def print_topology(topology: Topology) -> None:
    print("\nPeer-to-peer topology:")
    for client_id, neighbors in topology.items():
        print(f"  Client {client_id} neighbors: {neighbors}")


def run_experiment(args: argparse.Namespace) -> MetricsLogger:
    validate_args(args)
    defaults = Config()
    set_seed(args.seed)
    device = resolve_device(args.device)
    if args.security_mode in {"selective_he", "adaptive_hybrid"}:
        import_tenseal_or_raise()

    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / defaults.data_dir
    results_dir = project_root / defaults.results_dir
    logs_dir = results_dir / "logs"
    plots_dir = results_dir / "plots" / args.experiment_name
    logs_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    print(f"Experiment: {args.experiment_name}")
    print(f"Dataset: {args.dataset}")
    print(f"Security mode: {args.security_mode}")
    print(f"Device: {device}")
    if device == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")
    audit_chain = None
    product_audit = None
    if args.enable_blockchain:
        from blockchain import AuditBlockchain

        blockchain_configuration = build_blockchain_configuration(args, device)
        audit_chain = AuditBlockchain(
            experiment_name=args.experiment_name,
            configuration=blockchain_configuration,
            project_root=project_root,
        )
        print("Blockchain audit layer: enabled")
    if args.enable_audit:
        from audit import FederatedAuditLedger

        audit_configuration = build_blockchain_configuration(args, device)
        product_audit = FederatedAuditLedger(
            experiment_name=args.experiment_name,
            configuration=audit_configuration,
            output_root=results_dir / "audit_packages",
        )
        print("Product audit package: enabled")
    print(f"Loading {args.dataset}...")
    train_dataset, test_dataset, dataset_spec = get_datasets(args.dataset, str(data_dir))

    if args.split_type == "iid":
        client_loaders = create_iid_client_loaders(
            train_dataset, args.num_clients, args.batch_size, args.seed
        )
    else:
        client_loaders = create_non_iid_client_loaders(
            train_dataset,
            args.num_clients,
            args.batch_size,
            shards_per_client=2,
            seed=args.seed,
        )
    test_loader = get_test_loader(test_dataset, args.batch_size)

    topology = build_topology(args.topology, args.num_clients, args.seed)
    print_topology(topology)

    # Every peer begins from exactly the same seeded initialization.
    initial_model = SimpleMLP(
        input_shape=dataset_spec.input_shape,
        num_classes=dataset_spec.num_classes,
    )
    initial_state = {
        key: value.detach().clone() for key, value in initial_model.state_dict().items()
    }
    clients: List[Client] = []
    for client_id, train_loader in enumerate(client_loaders):
        model = SimpleMLP(
            input_shape=dataset_spec.input_shape,
            num_classes=dataset_spec.num_classes,
        )
        model.load_state_dict(initial_state)
        clients.append(
            Client(
                client_id=client_id,
                model=model,
                train_loader=train_loader,
                test_loader=test_loader,
                device=device,
                learning_rate=args.lr,
            )
        )

    model_size_bytes = estimate_model_size_bytes(initial_model)
    # Every adjacency-list entry represents one directed model transmission.
    transmissions_per_round = sum(len(neighbors) for neighbors in topology.values())
    communication_bytes = transmissions_per_round * model_size_bytes
    he_contexts = {}
    he_selected_param_names: List[str] = []
    he_selected_plain_bytes_per_message = 0
    if args.security_mode in {"selective_he", "adaptive_hybrid"}:
        he_selected_param_names = get_final_layer_param_names(initial_state)
        he_selected_plain_bytes_per_message = selected_plain_size_bytes(
            initial_state, he_selected_param_names
        )
        coeff_mod_bit_sizes = parse_coeff_mod_bits(args.he_coeff_mod_bits)
        context_start = time.perf_counter()
        he_contexts = {
            client.client_id: create_ckks_context(
                poly_modulus_degree=args.he_poly_modulus_degree,
                coeff_mod_bit_sizes=coeff_mod_bit_sizes,
                scale_bits=args.he_scale_bits,
            )
            for client in clients
        }
        print(f"Selective HE parameters: {he_selected_param_names}")
        print(
            f"CKKS contexts: {len(he_contexts)} target-specific contexts "
            f"created in {time.perf_counter() - context_start:.2f}s"
        )
        if args.security_mode == "adaptive_hybrid":
            print(
                "Adaptive policy: "
                f"{args.adaptive_policy} | HE target ratio: "
                f"{args.adaptive_he_target_ratio:.2f} | minimum HE targets: "
                f"{args.adaptive_min_he_targets}"
            )
    logger = MetricsLogger()

    print(
        f"\nStarting DFL: {args.num_clients} clients, "
        f"{args.num_rounds} rounds, {args.split_type} split\n"
    )

    for round_index in tqdm(range(1, args.num_rounds + 1), desc="DFL rounds"):
        round_start = time.perf_counter()

        round_start_states = {}
        if args.security_mode == "adaptive_hybrid":
            round_start_states = {
                client.client_id: client.get_state_dict() for client in clients
            }

        # Phase 1: every client trains only on its local partition.
        train_losses = [
            client.train_local(args.local_epochs) for client in clients
        ]

        # Phase 2: immutable snapshots guarantee synchronous aggregation.
        previous_states = {
            client.client_id: client.get_state_dict() for client in clients
        }
        new_states: Dict[int, Dict[str, torch.Tensor]] = {}
        masking_time_seconds = 0.0
        masking_overhead_bytes = 0
        seed_overhead_bytes = 0
        pairwise_masking_cancellation_error = 0.0
        he_encryption_time_seconds = 0.0
        he_aggregation_time_seconds = 0.0
        he_decryption_time_seconds = 0.0
        he_total_time_seconds = 0.0
        he_ciphertext_bytes = 0
        he_num_encrypted_values = 0
        he_plain_selected_bytes = 0
        he_reconstruction_max_error = 0.0
        adaptive_he_targets_count = 0
        adaptive_pairwise_targets_count = 0
        adaptive_he_target_ratio_actual = 0.0
        adaptive_avg_risk_score = 0.0
        adaptive_max_risk_score = 0.0
        adaptive_min_risk_score = 0.0
        adaptive_selected_targets = ""
        adaptive_threshold_used = 0.0
        adaptive_risk_scores_for_blockchain = {}

        if args.security_mode == "masking":
            masking_start = time.perf_counter()
            masks = {}
            masked_states = {}
            for client in clients:
                client_id = client.client_id
                # Round/client-derived seeds make masks reproducible but unique.
                mask_seed = args.seed + round_index * args.num_clients + client_id
                masks[client_id] = generate_mask_for_state_dict(
                    previous_states[client_id], seed=mask_seed
                )
                masked_states[client_id] = apply_mask(
                    previous_states[client_id], masks[client_id]
                )
                masking_overhead_bytes += len(topology[client_id]) * (
                    estimate_masking_overhead_bytes(masks[client_id])
                )

            for client in clients:
                # The client's own state stays local. Neighbor states cross the
                # simulated protected transport and are unmasked on receipt.
                states_to_average = [previous_states[client.client_id]]
                for neighbor_id in topology[client.client_id]:
                    states_to_average.append(
                        remove_mask(masked_states[neighbor_id], masks[neighbor_id])
                    )
                new_states[client.client_id] = average_state_dicts(states_to_average)
            masking_time_seconds = time.perf_counter() - masking_start
        elif args.security_mode == "pairwise_masking":
            masking_start = time.perf_counter()
            mask_size_bytes = estimate_masking_overhead_bytes(
                previous_states[clients[0].client_id]
            )

            for client in clients:
                target_client_id = client.client_id
                contributor_ids = [
                    target_client_id,
                    *topology[target_client_id],
                ]
                masked_contributions = build_masked_contributions_for_target(
                    target_client_id=target_client_id,
                    contributor_ids=contributor_ids,
                    previous_states=previous_states,
                    round_idx=round_index,
                    base_seed=args.seed,
                    device=device,
                )
                states_to_average = [
                    masked_contributions[contributor_id]
                    for contributor_id in contributor_ids
                ]
                masked_average = average_state_dicts(states_to_average)

                # This virtual baseline average is only a numerical debug check.
                # It is not a server model and is never used for client updates.
                baseline_average = average_state_dicts(
                    previous_states[contributor_id]
                    for contributor_id in contributor_ids
                )
                cancellation_error = max_state_dict_difference(
                    baseline_average, masked_average
                )
                pairwise_masking_cancellation_error = max(
                    pairwise_masking_cancellation_error, cancellation_error
                )
                new_states[target_client_id] = masked_average

                contributor_count = len(contributor_ids)
                pair_count = contributor_count * (contributor_count - 1) // 2
                masking_overhead_bytes += pair_count * mask_size_bytes
                seed_overhead_bytes += pair_count * 32

            masking_time_seconds = time.perf_counter() - masking_start
            if pairwise_masking_cancellation_error > 1e-6:
                tqdm.write(
                    "Warning: pairwise masking cancellation error exceeds "
                    f"tolerance: {pairwise_masking_cancellation_error:.3e}"
                )
        elif args.security_mode == "selective_he":
            for client in clients:
                target_client_id = client.client_id
                contributor_ids = [
                    target_client_id,
                    *topology[target_client_id],
                ]
                aggregated_state, he_metrics = selective_he_aggregate_for_target(
                    target_client_id=target_client_id,
                    contributor_ids=contributor_ids,
                    previous_states=previous_states,
                    target_context=he_contexts[target_client_id],
                    selected_param_names=he_selected_param_names,
                    device=device,
                )
                new_states[target_client_id] = aggregated_state
                he_encryption_time_seconds += float(
                    he_metrics["he_encryption_time_seconds"]
                )
                he_aggregation_time_seconds += float(
                    he_metrics["he_aggregation_time_seconds"]
                )
                he_decryption_time_seconds += float(
                    he_metrics["he_decryption_time_seconds"]
                )
                he_total_time_seconds += float(he_metrics["he_total_time_seconds"])
                he_ciphertext_bytes += int(he_metrics["he_ciphertext_bytes"])
                he_num_encrypted_values += int(
                    he_metrics["he_num_encrypted_values"]
                )
                he_plain_selected_bytes += int(
                    he_metrics["he_plain_selected_bytes"]
                )
                he_reconstruction_max_error = max(
                    he_reconstruction_max_error,
                    float(he_metrics["he_reconstruction_max_error"]),
                )
        elif args.security_mode == "adaptive_hybrid":
            risk_scores = compute_target_risk_scores(
                round_start_states=round_start_states,
                previous_states=previous_states,
                topology=topology,
                selected_param_names=he_selected_param_names,
                split_type=args.split_type,
            )
            adaptive_risk_scores_for_blockchain = dict(risk_scores)
            he_targets = select_he_targets(
                risk_scores=risk_scores,
                policy=args.adaptive_policy,
                he_target_ratio=args.adaptive_he_target_ratio,
                threshold=args.adaptive_risk_threshold,
                min_he_targets=args.adaptive_min_he_targets,
                round_idx=round_index - 1,
                he_every_n_rounds=args.adaptive_he_every_n_rounds,
            )
            risk_values = list(risk_scores.values())
            adaptive_he_targets_count = len(he_targets)
            adaptive_pairwise_targets_count = len(clients) - len(he_targets)
            adaptive_he_target_ratio_actual = len(he_targets) / len(clients)
            adaptive_avg_risk_score = sum(risk_values) / len(risk_values)
            adaptive_max_risk_score = max(risk_values)
            adaptive_min_risk_score = min(risk_values)
            adaptive_selected_targets = ";".join(
                str(client_id) for client_id in sorted(he_targets)
            )
            if args.adaptive_policy == "threshold":
                adaptive_threshold_used = args.adaptive_risk_threshold

            mask_size_bytes = estimate_masking_overhead_bytes(
                previous_states[clients[0].client_id]
            )
            for client in clients:
                target_client_id = client.client_id
                contributor_ids = [
                    target_client_id,
                    *topology[target_client_id],
                ]

                masking_start = time.perf_counter()
                masked_contributions = build_masked_contributions_for_target(
                    target_client_id=target_client_id,
                    contributor_ids=contributor_ids,
                    previous_states=previous_states,
                    round_idx=round_index,
                    base_seed=args.seed,
                    device=device,
                )
                states_to_average = [
                    masked_contributions[contributor_id]
                    for contributor_id in contributor_ids
                ]
                pairwise_averaged_state = average_state_dicts(states_to_average)
                baseline_average = average_state_dicts(
                    previous_states[contributor_id]
                    for contributor_id in contributor_ids
                )
                cancellation_error = max_state_dict_difference(
                    baseline_average, pairwise_averaged_state
                )
                pairwise_masking_cancellation_error = max(
                    pairwise_masking_cancellation_error, cancellation_error
                )
                masking_time_seconds += time.perf_counter() - masking_start

                contributor_count = len(contributor_ids)
                pair_count = contributor_count * (contributor_count - 1) // 2
                masking_overhead_bytes += pair_count * mask_size_bytes
                seed_overhead_bytes += pair_count * 32

                if target_client_id not in he_targets:
                    new_states[target_client_id] = pairwise_averaged_state
                    continue

                decrypted_selected, he_metrics = (
                    homomorphic_average_selected_params_only(
                        target_client_id=target_client_id,
                        contributor_ids=contributor_ids,
                        previous_states=previous_states,
                        target_context=he_contexts[target_client_id],
                        selected_param_names=he_selected_param_names,
                        device=device,
                    )
                )
                hybrid_state = OrderedDict(
                    (key, tensor.detach().clone())
                    for key, tensor in pairwise_averaged_state.items()
                )
                for name in he_selected_param_names:
                    hybrid_state[name] = decrypted_selected[name]
                new_states[target_client_id] = hybrid_state

                he_encryption_time_seconds += float(
                    he_metrics["he_encryption_time_seconds"]
                )
                he_aggregation_time_seconds += float(
                    he_metrics["he_aggregation_time_seconds"]
                )
                he_decryption_time_seconds += float(
                    he_metrics["he_decryption_time_seconds"]
                )
                he_total_time_seconds += float(he_metrics["he_total_time_seconds"])
                he_ciphertext_bytes += int(he_metrics["he_ciphertext_bytes"])
                he_num_encrypted_values += int(
                    he_metrics["he_num_encrypted_values"]
                )
                he_plain_selected_bytes += int(
                    he_metrics["he_plain_selected_bytes"]
                )
                he_reconstruction_max_error = max(
                    he_reconstruction_max_error,
                    float(he_metrics["he_reconstruction_max_error"]),
                )

            if pairwise_masking_cancellation_error > 1e-6:
                tqdm.write(
                    "Warning: adaptive pairwise cancellation error exceeds "
                    f"tolerance: {pairwise_masking_cancellation_error:.3e}"
                )
        else:
            # Preserve the original baseline aggregation path exactly.
            for client in clients:
                peer_ids = [client.client_id, *topology[client.client_id]]
                new_states[client.client_id] = average_state_dicts(
                    previous_states[peer_id] for peer_id in peer_ids
                )

        # Phase 3: updates are applied only after all averages are computed.
        for client in clients:
            client.set_state_dict(new_states[client.client_id])

        avg_test_loss, avg_test_accuracy, _ = evaluate_all_clients(
            clients, test_loader
        )
        avg_train_loss = sum(train_losses) / len(train_losses)
        elapsed = time.perf_counter() - round_start
        if args.security_mode == "masking":
            total_communication_bytes = communication_bytes + masking_overhead_bytes
        elif args.security_mode == "pairwise_masking":
            total_communication_bytes = communication_bytes + seed_overhead_bytes
        elif args.security_mode == "selective_he":
            plain_non_selected_bytes = (
                model_size_bytes - he_selected_plain_bytes_per_message
            )
            total_communication_bytes = (
                transmissions_per_round * plain_non_selected_bytes
                + he_ciphertext_bytes
            )
        elif args.security_mode == "adaptive_hybrid":
            adaptive_he_extra_bytes = max(
                0, he_ciphertext_bytes - he_plain_selected_bytes
            )
            total_communication_bytes = (
                communication_bytes
                + seed_overhead_bytes
                + adaptive_he_extra_bytes
            )
        else:
            total_communication_bytes = communication_bytes

        he_ciphertext_expansion_ratio = (
            he_ciphertext_bytes / he_plain_selected_bytes
            if he_plain_selected_bytes
            else 0.0
        )

        logger.log(
            round_number=round_index,
            avg_train_loss=avg_train_loss,
            avg_test_loss=avg_test_loss,
            avg_test_accuracy=avg_test_accuracy,
            communication_bytes=communication_bytes,
            round_time_seconds=elapsed,
            masking_time_seconds=masking_time_seconds,
            masking_overhead_bytes=masking_overhead_bytes,
            seed_overhead_bytes=seed_overhead_bytes,
            total_communication_bytes=total_communication_bytes,
            pairwise_masking_cancellation_error=(
                pairwise_masking_cancellation_error
            ),
            security_mode=args.security_mode,
            he_encryption_time_seconds=he_encryption_time_seconds,
            he_aggregation_time_seconds=he_aggregation_time_seconds,
            he_decryption_time_seconds=he_decryption_time_seconds,
            he_total_time_seconds=he_total_time_seconds,
            he_ciphertext_bytes=he_ciphertext_bytes,
            he_num_encrypted_values=he_num_encrypted_values,
            he_selected_param_count=len(he_selected_param_names),
            he_selected_param_names=";".join(he_selected_param_names),
            he_plain_selected_bytes=he_plain_selected_bytes,
            he_ciphertext_expansion_ratio=he_ciphertext_expansion_ratio,
            he_reconstruction_max_error=he_reconstruction_max_error,
            adaptive_policy=(
                args.adaptive_policy
                if args.security_mode == "adaptive_hybrid"
                else ""
            ),
            adaptive_he_targets_count=adaptive_he_targets_count,
            adaptive_pairwise_targets_count=adaptive_pairwise_targets_count,
            adaptive_he_target_ratio_actual=adaptive_he_target_ratio_actual,
            adaptive_avg_risk_score=adaptive_avg_risk_score,
            adaptive_max_risk_score=adaptive_max_risk_score,
            adaptive_min_risk_score=adaptive_min_risk_score,
            adaptive_selected_targets=adaptive_selected_targets,
            adaptive_threshold_used=adaptive_threshold_used,
        )
        if audit_chain is not None:
            audit_chain.add_round_block(
                round_number=round_index,
                metrics=logger.metrics[-1],
                client_states={
                    client.client_id: client.get_state_dict()
                    for client in clients
                },
                adaptive_risk_scores=adaptive_risk_scores_for_blockchain,
                adaptive_selected_targets=adaptive_selected_targets,
            )
        if product_audit is not None:
            product_audit.record_round(
                round_number=round_index,
                metrics=logger.metrics[-1],
                client_states={
                    client.client_id: client.get_state_dict()
                    for client in clients
                },
                adaptive_risk_scores=adaptive_risk_scores_for_blockchain,
                adaptive_selected_targets=adaptive_selected_targets,
            )
        round_summary = (
            f"Round {round_index}/{args.num_rounds} | "
            f"Train Loss: {avg_train_loss:.4f} | "
            f"Test Loss: {avg_test_loss:.4f} | "
            f"Test Acc: {avg_test_accuracy:.2f}% | "
            f"Comm: {total_communication_bytes / (1024**2):.2f} MiB"
        )
        if args.security_mode == "masking":
            round_summary += f" | Masking: {masking_time_seconds:.4f}s"
        elif args.security_mode == "pairwise_masking":
            round_summary += (
                f" | Masking: {masking_time_seconds:.4f}s"
                f" | Seed: {seed_overhead_bytes} B"
                f" | Cancel err: {pairwise_masking_cancellation_error:.3e}"
            )
        elif args.security_mode == "selective_he":
            round_summary += (
                f" | HE: {he_total_time_seconds:.4f}s"
                f" | Enc: {he_encryption_time_seconds:.4f}s"
                f" | Dec: {he_decryption_time_seconds:.4f}s"
            )
        elif args.security_mode == "adaptive_hybrid":
            round_summary += (
                f" | HE targets: {adaptive_he_targets_count}/{len(clients)}"
                f" | Risk max: {adaptive_max_risk_score:.4e}"
                f" | HE: {he_total_time_seconds:.4f}s"
                f" | Masking: {masking_time_seconds:.4f}s"
            )
        round_summary += f" | Time: {elapsed:.2f}s"
        tqdm.write(round_summary)

    csv_path = logs_dir / f"{args.experiment_name}_metrics.csv"
    logger.save_csv(str(csv_path))
    plot_accuracy(logger.metrics, str(plots_dir / "accuracy.png"))
    plot_loss(logger.metrics, str(plots_dir / "loss.png"))
    plot_round_time(logger.metrics, str(plots_dir / "round_time.png"))
    plot_communication(logger.metrics, str(plots_dir / "communication.png"))
    blockchain_artifacts = None
    if audit_chain is not None:
        blockchain_dir = results_dir / "blockchain"
        blockchain_artifacts = audit_chain.save_artifacts(blockchain_dir)
    audit_artifacts = None
    if product_audit is not None:
        audit_artifacts = product_audit.finalize()

    final = logger.metrics[-1]
    print(f"\nExperiment complete: {args.experiment_name}")
    print(f"Final average test accuracy: {final['avg_test_accuracy']:.2f}%")
    print(f"Metrics CSV: {csv_path}")
    print(f"Plots directory: {plots_dir}")
    if blockchain_artifacts is not None:
        print(f"Blockchain JSON: {blockchain_artifacts['chain']}")
        print(f"Blockchain verification report: {blockchain_artifacts['report']}")
        print(f"Blockchain plots directory: {blockchain_artifacts['plots']}")
    if audit_artifacts is not None:
        print(f"Audit package: {audit_artifacts['package']}")
        print(f"Audit ledger: {audit_artifacts['ledger']}")
        print(f"Audit verification report: {audit_artifacts['report']}")
        print(f"Audit plots directory: {audit_artifacts['plots']}")
    return logger


if __name__ == "__main__":
    run_experiment(parse_args())
