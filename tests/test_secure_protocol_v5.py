import dataclasses,tempfile,sys,unittest,copy
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from secure_protocol_v5.node import Node,RoundSpec
from secure_protocol_v5 import crypto as c
from secure_protocol_v4.core import Rejected,encode,decode,aggregate_tag

def policy(length=8):return RoundSpec('test-v5','fresh-epoch','p000',1,'model','schema',('p000','p001','p002'),length)
class VerifiedHE(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.spec=policy()
        self.nodes=[Node(n,self.spec,Path(self.tmp.name)/(n+'.db')) for n in self.spec.roster]
        roster={n.identity.name:n.registration() for n in self.nodes}
        for n in self.nodes:n.pin(roster)
        self.keys=[n.keygen() for n in self.nodes]
    def tearDown(self):
        for n in self.nodes:n.ledger.db.close()
        self.tmp.cleanup()
    def initialize(self):
        for n in self.nodes:n.set_keys(self.keys)
    def messages(self):return [n.contribution([(-1)**i*.125]*self.spec.length) for i,n in enumerate(self.nodes)]
    def test_ristretto_scalar_validation_and_signed_decoding(self):
        self.assertEqual(c.base(c.scalar(1)).hex(),'e2f2ae0a6abc4e71a884a961c500515f58e30b6aa582dd8db6a65945e08d2d76')
        raw=b'\xff'*64
        self.assertEqual(c.s.crypto_core_ristretto255_scalar_reduce(raw),c.scalar(int.from_bytes(raw,'little')))
        decoder=c.BoundedLog(100)
        for i in range(-100,101):self.assertEqual(decoder.decode(c.base(c.scalar(i))),i)
        with self.assertRaises(Rejected):decoder.decode(c.base(c.scalar(101)))
        with self.assertRaises(Rejected):c.point(b'\xff'*32)
        with self.assertRaises(Rejected):c.response(c.ORDER.to_bytes(32,'little'))
    def test_rogue_public_share_requires_possession(self):
        attacker=self.nodes[-1];raw=decode(self.keys[-1]['body']['payload']['data']);others=c.add(decode(self.keys[0]['body']['payload']['data'])[:32],decode(self.keys[1]['body']['payload']['data'])[:32])
        bad=c.sub(raw[:32],others)+raw[32:]
        messages=self.keys[:-1]+[attacker.identity.sign(self.spec,'keyshare',{'data':encode(bad)})]
        with self.assertRaisesRegex(Rejected,'proof of possession'):self.nodes[0].set_keys(messages)
        self.initialize();self.assertNotEqual(self.nodes[0].public,raw[:32])
    def test_key_proof_context_binding_and_own_key_pin(self):
        raw=decode(self.keys[0]['body']['payload']['data'])
        with self.assertRaises(Rejected):c.verify_key(bytes.fromhex(self.spec.tag),'p001',raw)
        altered=dataclasses.replace(self.spec,round=2)
        with self.assertRaises(Rejected):c.verify_key(bytes.fromhex(altered.tag),'p000',raw)
        rogue_secret,record=c.keygen(bytes.fromhex(self.spec.tag),'p000')
        bad=self.nodes[0].identity.sign(self.spec,'keyshare',{'data':encode(record)})
        with self.assertRaises(Rejected):self.nodes[0].set_keys([bad]+self.keys[1:])
    def test_signed_cancellation_and_copied_cipher_proofs_rejected(self):
        self.initialize();messages=self.messages();raw=decode(messages[2]['body']['payload']['data']);bad=[]
        for _,parts in c.chunks(raw,192,self.spec.length):bad.append(c.sub(c.IDENTITY,parts[0])+c.sub(c.IDENTITY,parts[1])+b''.join(parts[2:]))
        forged=self.nodes[0].identity.sign(self.spec,'contribution',{'data':encode(b''.join(bad))})
        messages[0]=forged
        with self.assertRaisesRegex(Rejected,'knowledge proof'):self.nodes[1].recompute(messages)
    def test_noncanonical_or_missing_cipher_proofs_rejected(self):
        self.initialize();messages=self.messages();raw=decode(messages[0]['body']['payload']['data'])
        for bad in [raw[:-1],b'\xff'*32+raw[32:],raw[:128]+c.ORDER.to_bytes(32,'little')+raw[160:]]:
            forged=self.nodes[0].identity.sign(self.spec,'contribution',{'data':encode(bad)})
            with self.assertRaises(Rejected):self.nodes[1].recompute([forged]+messages[1:])
    def test_all_party_recovery_dleq_and_replays(self):
        self.initialize();messages=self.messages();candidate=self.nodes[0].recompute(messages)
        with self.assertRaises(Rejected):self.nodes[1].release(messages,candidate,[])
        approvals=[n.approve(messages,candidate) for n in self.nodes]
        releases=[n.release(messages,candidate,approvals) for n in self.nodes]
        tag=aggregate_tag(self.spec,messages,encode(candidate));columns=[]
        for n,release in zip(self.nodes,releases):
            data=decode(release['body']['payload']['data'])
            columns.append(c.verify_partial(data,candidate,self.spec,n.keys[n.identity.name],tag,n.identity.name))
            with self.assertRaises(Rejected):c.verify_partial(c.add(data[:32],c.base(c.scalar(1)))+data[32:],candidate,self.spec,n.keys[n.identity.name],tag,n.identity.name)
        decoder=c.BoundedLog(3*self.spec.scale)
        for i,(_,C) in c.chunks(candidate,64,self.spec.length):
            total=c.IDENTITY
            for column in columns:total=c.add(total,column[i])
            self.assertEqual(decoder.decode(c.sub(C,total))/(3*self.spec.scale),.125/3)
        with self.assertRaises(Rejected):self.nodes[0].release(messages,candidate,approvals)
        with self.assertRaises(Rejected):self.nodes[0].approve(messages,candidate)
    def test_private_share_does_not_decrypt_individual_ciphertext(self):
        self.initialize();messages=self.messages();parts=next(c.chunks(decode(messages[1]['body']['payload']['data']),192,self.spec.length))[1]
        wrong=c.sub(parts[1],c.mul(self.nodes[0].secret,parts[0]))
        self.assertNotEqual(wrong,c.base(c.scalar(-.125*self.spec.scale)))
    def test_policy_bounds_no_bfv_fallback(self):
        self.initialize()
        with self.assertRaises(Rejected):self.nodes[0].contribution([2.]*self.spec.length)
        with self.assertRaises(Rejected):self.nodes[0].contribution([float('nan')]*self.spec.length)
        with self.assertRaises(Rejected):dataclasses.replace(self.spec,kind='he_bfv')
        with self.assertRaises(Rejected):dataclasses.replace(self.spec,bound=1e6)
        from secure_protocol_v4.node import Node as Legacy
        from secure_protocol_v4.core import RoundSpec as OldSpec
        old=OldSpec('retired','epoch','p000',1,'m','s',self.spec.roster)
        with self.assertRaisesRegex(Rejected,'retired'):Legacy('p000',old,Path(self.tmp.name)/'retired.db')
class TransportTests(unittest.TestCase):
    def test_production_default_has_no_diagnostic_signing_oracle(self):
        from secure_protocol_v5.transport import Group
        s=policy(2);values={name:[.125,-.125] for name in s.roster}
        with Group(s,values) as group:
            with self.assertRaises(Rejected):group.call(s.target,'test_forge',phase='keyshare',payload={})
            with self.assertRaises(Rejected):group.call(s.target,'test_single_share')
            group.keygen();group.set_keys();messages=group.contributions();candidate=group.average(messages)
            approvals=group.approvals(messages,candidate);releases=group.releases(messages,candidate,approvals)
            np.testing.assert_array_equal(group.recover(messages,candidate,releases),[.125,-.125])
        self.assertTrue(all(not p.is_alive() for p in group.processes))
if __name__=='__main__':unittest.main()
