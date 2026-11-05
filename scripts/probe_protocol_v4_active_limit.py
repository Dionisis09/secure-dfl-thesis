"""Synthetic red-team probe: demonstrate a limit, NOT an active-security gate.

One corrupt HE participant bypasses its local input checks and signs a ciphertext
derived from a peer's ciphertext. No real model/data or network service is used.
Success of this probe means malicious-participant privacy is NOT established.
"""
import json,sys,tempfile,hashlib
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from secure_protocol_v4.core import RoundSpec,encode,decode,digest
from secure_protocol_v4.node import Node

def cancellation_probe():
    spec=RoundSpec('active-limit-probe','synthetic-only','p000',1,'fixture','fixture-schema',('p000','p001','p002'),32,'he_bfv')
    from secure_protocol_v4.openfhe_backend import MultipartyBFV
    public=MultipartyBFV(parties=3)
    with tempfile.TemporaryDirectory() as folder:
        nodes=[Node(n,spec,Path(folder)/(n+'.sqlite'),public.context(),unsafe_legacy_reproduction=True) for n in spec.roster]
        try:
            roster={n.identity.name:n.registration() for n in nodes}
            for node in nodes:node.pin(roster)
            chain=[];previous=None
            for node in nodes:
                message=node.keygen(previous,chain);chain.append(message);previous=decode(message['body']['payload']['key'])
            for node in nodes:node.set_key(chain)
            rng=np.random.default_rng(901)
            victim=rng.uniform(-.1,.1,spec.length);other=rng.uniform(-.1,.1,spec.length)
            victim_message=nodes[1].contribution(victim);other_message=nodes[2].contribution(other)
            # Attack construction uses only the other party's public ciphertext.
            ct=public.ciphertext(decode(other_message['body']['payload']['data']))
            negative=public.cc.EvalNegate(ct)
            corrupt=nodes[0]
            corrupt.own=corrupt.identity.sign(spec,'contribution',{'data':encode(public.dump(negative))})
            messages=[corrupt.own,victim_message,other_message]
            candidate=public.average([decode(m['body']['payload']['data']) for m in messages],3)
            approvals=[node.approve(messages,candidate) for node in nodes]
            releases=[node.release(messages,candidate,approvals) for node in nodes]
            mean=public.fusion([decode(m['body']['payload']['data']) for m in releases],spec)
            error=float(np.max(np.abs(3*mean-victim)))
            exposed=error<1e-4
            result=dict(attack='adaptive_ciphertext_cancellation',
                all_approvals_accepted=True,victim_recovered_from_authorized_mean=exposed,
                max_absolute_reconstruction_error=error)
            if not exposed:raise RuntimeError('probe inconclusive; do not infer active security')
            return result
        finally:
            for node in nodes:node.ledger.db.close()

def rogue_key_probe():
    from secure_protocol_v4.openfhe_backend import MultipartyBFV
    spec=RoundSpec('rogue-key-probe','synthetic-only','p000',1,'fixture','fixture-schema',('p000','p001','p002'),32,'he_bfv')
    public=MultipartyBFV(parties=3)
    with tempfile.TemporaryDirectory() as folder:
        nodes=[Node(n,spec,Path(folder)/(n+'.sqlite'),public.context(),unsafe_legacy_reproduction=True) for n in spec.roster]
        try:
            roster={n.identity.name:n.registration() for n in nodes}
            for node in nodes:node.pin(roster)
            chain=[];previous=None
            for node in nodes[:-1]:
                message=node.keygen(previous,chain);chain.append(message);previous=decode(message['body']['payload']['key'])
            # Corrupt final participant signs an unrelated key instead of a joint-key extension.
            corrupt=nodes[-1];rogue=public.cc.KeyGen()
            chain.append(corrupt.identity.sign(spec,'keygen',dict(previous=digest(previous),key=encode(public.dump(rogue.publicKey)))))
            for node in nodes:node.set_key(chain)
            victim=np.random.default_rng(902).uniform(-.1,.1,spec.length)
            message=nodes[0].contribution(victim)
            plain=public.cc.Decrypt(rogue.secretKey,public.ciphertext(decode(message['body']['payload']['data'])))
            plain.SetLength(spec.length)
            decoded=np.asarray(plain.GetPackedValue(),dtype=np.int64)
            decoded=np.where(decoded>public.MODULUS//2,decoded-public.MODULUS,decoded)/public.SCALE
            error=float(np.max(np.abs(decoded-victim)));exposed=error<1/public.SCALE
            if not exposed:raise RuntimeError('rogue-key probe inconclusive; do not infer active security')
            return dict(attack='signed_rogue_final_public_key',honest_nodes_accepted_key=True,
                individual_ciphertext_decrypted_without_approvals=exposed,max_absolute_reconstruction_error=error)
        finally:
            for node in nodes:node.ledger.db.close()

def main():
    attacks=[cancellation_probe(),rogue_key_probe()]
    root=Path(__file__).resolve().parents[1]
    files=sorted((root/'src/secure_protocol_v4').glob('*.py'))+[Path(__file__).resolve()]
    hashes={str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest() for p in files}
    print(json.dumps(dict(status='active_security_limits_confirmed',synthetic_only=True,
        participants=3,honest_participants=2,corrupt_participants=1,attacks=attacks,source_sha256=hashes,
        conclusion='Signatures do not prove honest joint-key generation or plaintext possession. Do not deploy this prototype against malicious participants.'),indent=2))

if __name__=='__main__':main()
