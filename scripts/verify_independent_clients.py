"""Trusted deployment/test operator; never run inside the coordinator sandbox."""
import argparse,json,os,sys,time,subprocess,shutil,signal
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
import torch,numpy as np
from independent_clients.provision import provision
from independent_clients.network import RemoteClients
from independent_clients.common import atomic_json,decode_state,encode_state,apply_aggregate,schema_for
from secure_protocol_v6.training_adapter import state_hash
from secure_protocol_v4.core import digest

parser=argparse.ArgumentParser();parser.add_argument('--model',choices=['mlp','cnn'],required=True);parser.add_argument('--clients',type=int,default=3)
parser.add_argument('--job',required=True);parser.add_argument('--data-archive',required=True)
parser.add_argument('--recovery',action='store_true');args=parser.parse_args()
import re
if not re.fullmatch('[a-z][a-z0-9_-]{0,63}',args.job):raise ValueError('job must be a new simple identifier')
jobroot=root/'private-jobs'/args.job;processes=[];coordinators=[]
env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1',CUBLAS_WORKSPACE_CONFIG=':4096:8')
archive=Path(args.data_archive).resolve()
provision(jobroot,archive,model=args.model,clients=args.clients,rounds=2 if args.recovery else 1,
    train_samples=args.clients*32,batch_size=16,device='cpu')
config=json.loads((jobroot/'coordinator/config.json').read_text());job=config['job'];ready=[]
def start(name):
    pdir=jobroot/name
    log=(pdir/'service.log').open('ab')
    process=subprocess.Popen([sys.executable,'-u',str(root/'scripts/independent_client.py'),'--config',str(pdir/'config.json')],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    log.close();processes.append(process);return process
try:
    for name in job['roster']:start(name)
    remote=RemoteClients(config)
    deadline=time.monotonic()+180
    for name in job['roster']:
        while True:
            if any(p.poll() is not None for p in processes):
                for n in job['roster']:
                    print(n,(jobroot/n/'service.log').read_text()[-4000:],flush=True)
                raise RuntimeError('client startup failed')
            try:ready.append(remote.call(name,'status'));break
            except (OSError,ConnectionError):
                if time.monotonic()>deadline:raise
                time.sleep(1)
    remote.close()
    config['boundary_probes']=dict(paths=[str(jobroot/n/file) for n in job['roster'] for file in ['data.npz','identity.json','checkpoint.pt','tls.key']],pids=[r['pid'] for r in ready])
    atomic_json(jobroot/'coordinator/config.json',config)
    def coordinate(extra=()):
        command=[sys.executable,'-u',str(root/'scripts/run_independent_training.py'),'--config',str(jobroot/'coordinator/config.json'),'--verify-boundary',*extra]
        process=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        coordinators.append(process)
        with (jobroot/'coordinator/runner.log').open('a') as stream:
            for line in process.stdout:
                stream.write(line);stream.flush();print(line,end='',flush=True)
        if process.wait():raise RuntimeError('coordinator failed')
    coordinate(['--stop-after-commit-intent'] if args.recovery else [])
    # Preserve real protocol calls before the intentionally empty no-op resume.
    shutil.copyfile(jobroot/'coordinator/rpc_audit.json',jobroot/'coordinator/rpc_audit_first.json')
    if args.recovery:
        # A mixed distributed commit: one client committed, the others pending.
        journal=json.loads((jobroot/'coordinator/checkpoint.json').read_text())
        remote=RemoteClients(config)
        remote.call(job['roster'][0],'commit',receipts=journal['pending']['receipts']);remote.close()
        # Crash/restart every independent service after pending global state was fsynced.
        for process in processes:process.terminate()
        for process in processes:process.wait(timeout=15)
        processes.clear();ready=[]
        for name in job['roster']:start(name)
        remote=RemoteClients(config);deadline=time.monotonic()+180
        for name in job['roster']:
            while True:
                try:ready.append(remote.call(name,'status'));break
                except (OSError,ConnectionError):
                    if time.monotonic()>deadline:raise
                    time.sleep(1)
        remote.close()
        assert not ready[0]['pending'] and ready[0]['completed_round']==1
        assert all(r['pending'] and r['completed_round']==0 for r in ready[1:])
        config['boundary_probes']['pids']=[r['pid'] for r in ready];atomic_json(jobroot/'coordinator/config.json',config)
        coordinate(['--max-new-rounds','1'])
        shutil.copyfile(jobroot/'coordinator/rpc_audit.json',jobroot/'coordinator/rpc_audit_resumed.json')
    # Complete-run resume must send no train/release calls or change the global journal.
    before=digest((jobroot/'coordinator/checkpoint.json').read_bytes())
    client_before=[digest((jobroot/n/'checkpoint.pt').read_bytes()) for n in job['roster']]
    coordinate()
    after=digest((jobroot/'coordinator/checkpoint.json').read_bytes());assert before==after
    assert client_before==[digest((jobroot/n/'checkpoint.pt').read_bytes()) for n in job['roster']]
    verification=json.loads((jobroot/'coordinator/verification.json').read_text());assert verification['new_rounds']==0
    calls=json.loads((jobroot/'coordinator/rpc_audit.json').read_text());assert not any(c['op'] in ('train','he_release') and c['ok'] for c in calls)
    journal=json.loads((jobroot/'coordinator/checkpoint.json').read_text())
    checkpoints=[torch.load(jobroot/n/'checkpoint.pt',map_location='cpu',weights_only=False) for n in job['roster']]
    assert all(state_hash(c['global_state'])==journal['records'][-1]['global_state_hash'] and c['round']==job['rounds'] for c in checkpoints)
    # Trusted, separately invoked audit: recompute local SGD from each client's
    # private shard and private RNG seed; never expose this oracle to the trainer.
    from independent_clients.service import PrivateImages
    from client import Client
    from matched_models import build_model
    from torch.utils.data import DataLoader
    import random
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True);torch.manual_seed(job['initial_seed'])
    template=build_model(job['model'],tuple(job['input_shape']));base=decode_state((jobroot/'coordinator/initial_state.b64').read_text(),template.state_dict())
    generators=[];datasets=[];configs=[]
    for n in job['roster']:
        cfg=json.loads((jobroot/n/'config.json').read_text());configs.append(cfg)
        generators.append(torch.Generator().manual_seed(cfg['training_seed']))
        datasets.append(PrivateImages(jobroot/n/'data.npz',job['input_shape'],32))
    hs,bs=schema_for(base);checks=[]
    for number in range(1,job['rounds']+1):
        htotal=np.zeros(2570,dtype=np.int64);btotal=np.zeros(sum(s['size'] for s in bs),dtype=np.int64)
        from secure_protocol_v4.model_adapter import flatten
        for i,cfg in enumerate(configs):
            model=build_model(job['model'],tuple(job['input_shape']));model.load_state_dict(base)
            loader=DataLoader(datasets[i],batch_size=job['batch_size'],shuffle=True,generator=generators[i])
            client=Client(i,model,loader,'cpu',job['learning_rate'])
            random.seed(cfg['training_seed']);np.random.seed(cfg['training_seed']%(2**32));torch.manual_seed(cfg['training_seed'])
            client.train_local(job['local_epochs']);state=client.get_state_dict()
            delta={n:state[n]-v for n,v in base.items() if v.is_floating_point()}
            hv,_=flatten(delta,['head.weight','head.bias']);bv,_=flatten(delta,[s['name'] for s in bs])
            htotal+=np.rint(hv*job['scale']).astype(np.int64);btotal+=np.rint(bv*job['scale']).astype(np.int64)
            del client,model
        base=apply_aggregate(job,base,htotal/(job['scale']*args.clients),btotal/(job['scale']*args.clients))
        assert state_hash(base)==journal['records'][number-1]['global_state_hash'],('independent SGD oracle mismatch',number)
        checks.append(dict(round=number,full_state_exact=True,global_hash=state_hash(base)))
    result=dict(status='verified',job_id=job['job_id'],model=args.model,clients=args.clients,rounds=job['rounds'],
        aggregate_only_coordinator=True,private_file_denials=4*args.clients,memory_denials=args.clients,device='cpu',
        range_proofs=True,full_backbone_masking=True,independent_auditor_quantized_controls=checks,
        client_checkpoints_agree=True,complete_resume_noop=True,coordinator_checkpoint_unchanged_on_noop=True,
        client_checkpoints_unchanged_on_noop=True,partial_commit_idempotence_verified=args.recovery,
        crash_restart_after_pending_commit_verified=args.recovery,scope='real CIFAR10 bounded functional pilot; trusted offline auditor and host admin; not accuracy benchmark')
    files=sorted((root/'src').rglob('*.py'))+[root/'scripts/independent_client.py',root/'scripts/run_independent_training.py',Path(__file__).resolve()]
    result['source_sha256']={p.relative_to(root).as_posix():digest(p.read_text(encoding='utf-8').encode()) for p in files}
    result['training_source_hash']=job['source_hash']
    result['native_binary_sha256']=job['native_binary_sha256']
    output=root/'results'/'independent_clients'/args.job;output.mkdir(parents=True,exist_ok=True)
    for name in ['verification.json','boundary_probe.json','rpc_audit.json','rpc_audit_first.json']+(['rpc_audit_resumed.json'] if args.recovery else []):
        shutil.copyfile(jobroot/'coordinator'/name,output/name)
    atomic_json(output/'independent_audit.json',result)
    atomic_json(output/'public_job.json',job)
    print(json.dumps(result),flush=True)
finally:
    for process in [*processes,*coordinators]:
        if process.poll() is None:process.terminate()
    for process in [*processes,*coordinators]:
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:process.kill();process.wait()
    print('ALL CLIENT SERVICES STOPPED',flush=True)
