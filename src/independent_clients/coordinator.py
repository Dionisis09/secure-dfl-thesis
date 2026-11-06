"""Coordinator handles public global states and protected transcripts only.

It neither imports Client/PrivateImages nor reads a training dataset. No local
model states, optimizer states or local RNGs enter this process or its checkpoint.
"""
import json
import os
import time
import uuid
from pathlib import Path
import numpy as np
import torch
from matched_models import build_model
from secure_protocol_v4.core import Rejected,canonical,digest,encode,complete
from secure_protocol_v6.chunked import aggregate_group
from secure_protocol_v6.training_adapter import state_hash
from .common import validate_job,blob_spec,he_spec,apply_aggregate,HEView,encode_state,decode_state,atomic_json,run_lock,round_enrollment
from .network import RemoteClients,Segment


def save_journal(root,journal):
    # Contains only an authorized global model and signed public protocol receipts.
    path=root/'checkpoint.json';temp=root/'checkpoint.json.tmp'
    with temp.open('w') as stream:
        os.fchmod(stream.fileno(),0o600)
        json.dump(journal,stream);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def execute(config,*,isolation,max_new_rounds=0,probes=(),stop_after_commit_intent=False):
    root=Path(config['private_dir']);job=validate_job(config['job'])
    torch.set_num_threads(1);torch.manual_seed(job['initial_seed']);torch.use_deterministic_algorithms(True)
    model=build_model(job['model'],tuple(job['input_shape']))
    base=decode_state((root/'initial_state.b64').read_text(),model.state_dict())
    if state_hash(base)!=job['initial_state_hash']:raise Rejected('initial state mismatch')
    with run_lock(root/'run.lock'):
        journal=dict(job_id=job['job_id'],completed_round=0,global_state=encode_state(base),records=[],pending=None)
        if (root/'checkpoint.json').exists():
            journal=json.loads((root/'checkpoint.json').read_text())
            if journal['job_id']!=job['job_id']:raise Rejected('coordinator checkpoint policy mismatch')
            base=decode_state(journal['global_state'],base)
        else:save_journal(root,journal)
        remote=RemoteClients(config,parallelism=config.get('parallelism',4))
        try:
            # Test unsupported exfiltration commands through the actual service API.
            rejected=[]
            for operation,args in probes:
                try:remote.call(job['roster'][0],operation,**args)
                except Rejected:rejected.append(operation)
                else:raise Rejected('forbidden API operation succeeded')
            if journal['pending']:
                pending=journal['pending']
                responses=remote.parallel('commit',receipts=pending['receipts'])
                if any(r['global_state_hash']!=pending['global_hash'] for r in responses):raise Rejected('recovered commit mismatch')
                base=decode_state(pending['global_state'],base)
                journal.update(completed_round=pending['round'],global_state=pending['global_state'],pending=None)
                journal['records'].append(pending['record']);save_journal(root,journal)
            statuses=remote.parallel('status')
            for item in statuses:
                if (item['job_id']!=job['job_id'] or item['completed_round']!=journal['completed_round'] or
                    item['global_state_hash']!=state_hash(base) or item['pending'] or
                    item['registration']!=job['enrollment'][item['name']] or
                    not item['isolation']['filesystem_restricted'] or not item['isolation']['non_dumpable'] or
                    not item['isolation'].get('seccomp_enforced') or not item['isolation'].get('tcp_ports_restricted')):
                    raise Rejected('client policy/state/isolation mismatch')
            initial=journal['completed_round']
            for number in range(initial+1,job['rounds']+1):
                if max_new_rounds and number-initial>max_new_rounds:break
                started=time.monotonic();epoch=uuid.uuid4().hex;bh=state_hash(base)
                print(json.dumps(dict(stage='client_local_training',round=number,clients=len(job['roster']))),flush=True)
                ready=remote.parallel('train',round=number,epoch=epoch,base=bh)
                round_roster,bs=round_enrollment(job,base,number,epoch,ready)
                enrolled=remote.parallel('enroll_round',messages=ready)
                if any(item!={'context':bs.tag} for item in enrolled):raise Rejected('ephemeral round enrollment disagreement')
                blob=Segment(remote,'blob',bs);bm,commitments=aggregate_group(blob)
                hs=he_spec(job,base,number,epoch,commitments,bm,round_roster)
                contexts=remote.parallel('he_begin')
                if any(c!={'context':hs.tag} for c in contexts):raise Rejected('HE/backbone binding disagreement')
                he=Segment(remote,'he',hs);keys=he.parallel('keygen');he.parallel('set_keys',messages=keys)
                messages=he.parallel('contribute');view=HEView(hs,job['enrollment'],keys,parallelism=he.parallelism)
                candidate=view.average(messages)
                approvals=he.parallel('approve',messages=messages,candidate=encode(candidate))
                releases=he.parallel('release',messages=messages,candidate=encode(candidate),approvals=approvals)
                hm=np.asarray(view.recover(messages,candidate,releases))
                result=apply_aggregate(job,base,hm,bm);gh=state_hash(result)
                receipts=remote.parallel('finalize',messages=messages,candidate=encode(candidate),releases=releases)
                items=complete(receipts,bs,'global_ready',job['enrollment'])
                if any(v!=dict(global_hash=gh,round=number) for v in items.values()):raise Rejected('final client/coordinator aggregate mismatch')
                record=dict(round=number,clients=len(job['roster']),global_state_hash=gh,
                    full_client_consensus=True,head_range_proofs=True,full_backbone_masking=True,
                    elapsed_seconds=time.monotonic()-started,plaintext_local_states_received=False)
                # Persist commit intent before contacting any client: retry is idempotent.
                journal['pending']=dict(round=number,global_hash=gh,global_state=encode_state(result),receipts=receipts,record=record)
                save_journal(root,journal)
                if stop_after_commit_intent:
                    atomic_json(root/'rpc_audit.json',remote.calls)
                    atomic_json(root/'verification.json',dict(status='paused_at_durable_commit_intent',round=number,job_id=job['job_id']))
                    print(json.dumps(dict(stage='durable_commit_intent_paused',round=number)),flush=True)
                    return
                responses=remote.parallel('commit',receipts=receipts)
                if any(r!=dict(name=name,completed_round=number,global_state_hash=gh) for name,r in zip(job['roster'],responses)):
                    raise Rejected('commit acknowledgement mismatch')
                base=result;journal.update(completed_round=number,global_state=encode_state(base),pending=None)
                journal['records'].append(record);save_journal(root,journal)
                print(json.dumps(dict(stage='committed',round=number,global_state_hash=gh)),flush=True)
            receipt=dict(status='completed' if journal['completed_round']==job['rounds'] else 'paused',
                job_id=job['job_id'],model=job['model'],clients=len(job['roster']),completed_rounds=journal['completed_round'],
                new_rounds=journal['completed_round']-initial,records=journal['records'],isolation=isolation,
                plaintext_local_states_received=False,local_optimizer_states_received=False,
                plaintext_control_computed_by_coordinator=False,forbidden_operations_rejected=rejected,
                request_bytes=remote.request_bytes,response_bytes=remote.response_bytes,
                scope='Independent sandboxed clients; trusted provisioning/host admin; full uniform topology; no DP/poisoning/dropout guarantee')
            atomic_json(root/'verification.json',receipt)
            atomic_json(root/'rpc_audit.json',remote.calls)
            print(json.dumps({k:v for k,v in receipt.items() if k not in ('records','isolation')}),flush=True)
            return receipt
        finally:remote.close()
