"""Opaque message router: never sees neighborhood or local model plaintext."""
import json,math,os,time,uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from secure_protocol_v4.core import complete,canonical,digest,Rejected
from independent_clients.network import RemoteClients
from independent_clients.common import atomic_json,run_lock
from .protocol import control,signed_subset,phases

def run(config,profile,max_new_rounds=0,preflight_only=False):
    root=Path(config['private_dir']);job=config['job'];remote=RemoteClients(config,parallelism=2,audit_mode='aggregate')
    path=root/'journal.json'
    with run_lock(root/'run.lock'):
        if config.get('boundary_probes'):
            from independent_clients.isolation import denied_probes
            probes=config['boundary_probes'];profile['denial_probes']=denied_probes(probes['paths'],probes['pids'])
            atomic_json(root/'boundary.json',profile)
        journal=json.loads(path.read_text()) if path.exists() else dict(job_id=job['job_id'],completed=0,records=[],active=None,pending=None)
        if journal['job_id']!=job['job_id']:raise Rejected('journal job mismatch')
        start=journal['completed']
        def checkpoint():atomic_json(path,journal)
        def parallel(names,op,**args):
            with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(lambda n:remote.call(n,op,**args),names))
        def group_run(definition,report=None):
            names=definition['roster'];gid=definition['id']
            meta=parallel(names,'prepare_report',kind=report) if report else parallel(names,'begin_group',group=gid)
            if len({canonical(m) for m in meta})!=1:raise Rejected('group shape disagreement')
            length=meta[0]['length'];split=meta[0]['split']
            for phase,index,route in phases(length,split):
                acks=parallel(names,'act',group=gid,phase=phase,index=index)
                if phase=='he_contribution':
                    group_stats.append(dict(group=gid,native_ciphertext_bytes=sum(a['native_ciphertext_bytes'] for a in acks),range_proof_bytes=sum(a['range_proof_bytes'] for a in acks)))
                if route:
                    # One sender/recipient envelope at a time bounds memory and
                    # avoids a >64MiB HE fanout/transcript RPC at50 clients.
                    for sender in names:
                        for recipient in names:
                            envelope=remote.call(sender,'emit',group=gid,phase=phase,index=index,recipient=recipient)
                            remote.call(recipient,'ingest',group=gid,phase=phase,index=index,owner=sender,envelope=envelope)
            receipts=parallel(names,'group_ready',group=gid)
            items=signed_subset(receipts,spec,'group_ready',job['enrollment'],names)
            if len({p['state_hash'] for p in items.values()})!=1 or any(p['group']!=gid for p in items.values()):raise Rejected('group hash disagreement')
            if report:
                values=parallel(names,'accept_report',kind=report)
                if len({canonical(v) for v in values})!=1:raise Rejected('metric mean disagreement')
                return values[0]['values']
            parallel(names,'group_accept',group=gid,receipts=receipts)
        try:
            if preflight_only:
                statuses=remote.parallel('status')
                if any(s['job_id']!=job['job_id'] or not s['isolation']['seccomp_enforced'] or not s['isolation']['filesystem_restricted'] for s in statuses):raise Rejected('deployment policy mismatch')
                receipt=dict(status='preflight_only',job_id=job['job_id'],clients=len(statuses),completed_rounds=journal['completed'],records=journal['records'],
                    isolation=profile,no_training_performed=True,coordinator_receives_individual_or_neighborhood_models=False)
                atomic_json(root/'verification.json',receipt);return receipt
            if journal['pending']:
                pending=journal['pending'];responses=remote.parallel('commit',receipts=pending['receipts'])
                expected={m['body']['sender']:m['body']['payload']['state_hash'] for m in pending['receipts']}
                if any(r['state_hash']!=expected[r['name']] for r in responses):raise Rejected('commit recovery mismatch')
                journal['completed']=pending['round'];journal['records'].append(pending['record']);journal['pending']=None;journal['active']=None;checkpoint()
                journal['records'][-1]['timing_complete']=False;checkpoint()
            while journal['completed']<job['config']['rounds']:
                if (root/'pause.request').exists():break
                if max_new_rounds and journal['completed']-start>=max_new_rounds:break
                number=journal['completed']+1;started=time.monotonic()
                group_stats=[];request_start=remote.request_bytes;response_start=remote.response_bytes
                if journal['active'] is None:journal['active']=dict(round=number,epoch=uuid.uuid4().hex);checkpoint()
                active=journal['active'];spec=control(job,number,active['epoch'])
                # Serial GPU ownership. The private service replaces its own PID
                # with a GPU worker and returns as a CPU service after training.
                for name in job['roster']:
                    remote.call(name,'train',round=number,epoch=active['epoch'])
                    deadline=time.monotonic()+job.get('train_timeout_seconds',7200)
                    while True:
                        if time.monotonic()>deadline:raise TimeoutError('private training timeout')
                        try:status=remote.call(name,'status')
                        except (OSError,ConnectionError):time.sleep(.3);continue
                        if status['phase'].startswith('failed'):raise RuntimeError('private training worker could not start')
                        if status['phase']=='trained':break
                        time.sleep(.3)
                statuses=remote.parallel('status');messages=[s['ready'] for s in statuses]
                if job['config']['training_device']=='cuda' and any(s['training_execution']['device']!='cuda' or s['training_execution']['peak_GPU_allocated']<=0 for s in statuses):raise Rejected('GPU training proof missing')
                training_stage_seconds=time.monotonic()-started
                complete(messages,spec,'trained',job['enrollment']);remote.parallel('enroll',messages=messages)
                aggregation_start=time.monotonic()
                for definition in job['groups']:group_run(definition)
                aggregation_seconds=time.monotonic()-aggregation_start;reporting_start=time.monotonic()
                report=dict(id='report_metrics',roster=job['roster'],mode='pairwise_masking',targets=[])
                means=group_run(report,'metrics')
                if number==job['config']['rounds'] and job['config']['test_policy']!='never':group_run(dict(report,id='report_test'),'test')
                receipts=remote.parallel('round_ready');items=complete(receipts,spec,'round_ready',job['enrollment'])
                if len({canonical(v['metrics']) for v in items.values()})!=1:raise Rejected('global metric consensus failed')
                record=dict(round=number,metrics=next(iter(items.values()))['metrics'],seconds=time.monotonic()-started,
                    training_execution=[s['training_execution'] for s in statuses],
                    request_bytes=remote.request_bytes-request_start,response_bytes=remote.response_bytes-response_start,
                    training_stage_seconds=training_stage_seconds,aggregation_seconds=aggregation_seconds,reporting_seconds=time.monotonic()-reporting_start,
                    HE_group_stats=group_stats,logical_HE_targets=len(job['HE_targets']) if job['config']['mode']=='adaptive_hybrid' else len(job['roster']) if job['config']['mode'] in ('selective_he','hybrid_pairwise_head_he') else 0,
                    unique_mixing_groups=len(job['groups']),timing_complete=False,
                    individual_or_neighborhood_model_plaintexts_received=False)
                journal['pending']=dict(round=number,receipts=receipts,record=record);checkpoint()
                commit_start=time.monotonic()
                responses=remote.parallel('commit',receipts=receipts)
                if any(r['round']!=number or r['state_hash']!=items[r['name']]['state_hash'] for r in responses):raise Rejected('commit mismatch')
                record.update(commit_seconds=time.monotonic()-commit_start,seconds=time.monotonic()-started,timing_complete=True)
                journal.update(completed=number,pending=None,active=None);journal['records'].append(record);checkpoint()
                atomic_json(root/'progress.json',dict(completed=number,planned=job['config']['rounds'],job_id=job['job_id']))
                print(json.dumps(dict(stage='committed',round=number,metrics=record['metrics'])),flush=True)
            receipt=dict(status='completed' if journal['completed']==job['config']['rounds'] else 'paused',job_id=job['job_id'],
                completed_rounds=journal['completed'],records=journal['records'],isolation=profile,
                coordinator_receives_individual_or_neighborhood_models=False,source_hash=job['source_hash'])
            atomic_json(root/'verification.json',receipt)
            atomic_json(root/'rpc_audit.json',dict(scope='bounded aggregate RPC metadata; no payloads',totals=list(remote.audit_totals.values()),first_calls=remote.calls))
            return receipt
        finally:remote.close()
