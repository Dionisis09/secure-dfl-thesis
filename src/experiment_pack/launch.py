"""Trusted deployment supervisor; coordinator is a separate confined process."""
import json,os,shutil,subprocess,sys,time
from pathlib import Path
from .manifest import digest

def launch(root,*,max_new_rounds=0,wall_limit_seconds=7*86400,preflight_only=False):
    from independent_clients.common import run_lock
    with run_lock(Path(root)/'supervisor.lock'):
        return _launch(root,max_new_rounds=max_new_rounds,wall_limit_seconds=wall_limit_seconds,preflight_only=preflight_only)

def _launch(root,*,max_new_rounds=0,wall_limit_seconds=7*86400,preflight_only=False):
    from independent_clients.common import atomic_json
    from independent_clients.network import RemoteClients
    root=Path(root).resolve();config=json.loads((root/'coordinator/config.json').read_text());children=[];coordinator=None
    from cryptography import x509
    import datetime
    certificate=x509.load_pem_x509_certificate((root/'coordinator/tls.pem').read_bytes())
    if certificate.not_valid_after_utc<datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=8):
        from .provision import refresh_transport
        refresh_transport(root,config['job']['roster'])
    code=Path(__file__).resolve().parents[2];env=dict(os.environ,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
    def start(role,folder):
        stream=(folder/'runner.log').open('ab')
        process=subprocess.Popen([sys.executable,'-u',str(code/'scripts/pack_role.py'),'--role',role,'--config',str(folder/'config.json'),*(['--max-new-rounds',str(max_new_rounds)] if role=='coordinator' else []),*(['--preflight-only'] if role=='coordinator' and preflight_only else [])],
            env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        stream.close();return process
    started=time.monotonic()
    try:
        for name in config['job']['roster']:children.append(start('client',root/name))
        remote=RemoteClients(config);deadline=time.monotonic()+600;statuses=[]
        try:
            for name in config['job']['roster']:
                while True:
                    if any(p.poll() is not None for p in children):raise RuntimeError('client startup failed; inspect private client log')
                    if time.monotonic()>deadline:raise TimeoutError('client enrollment startup timeout')
                    try:statuses.append(remote.call(name,'status'));break
                    except (OSError,ConnectionError):time.sleep(.5)
        finally:remote.close()
        config['boundary_probes']=dict(paths=[str(root/n/f) for n in config['job']['roster'] for f in ['data.npz','identity.json','checkpoint.pt','tls.key']],pids=[s['pid'] for s in statuses])
        atomic_json(root/'coordinator/config.json',config)
        coordinator=start('coordinator',root/'coordinator')
        while coordinator.poll() is None:
            if any(p.poll() is not None for p in children):raise RuntimeError('private client/worker exited; no automatic crypto retry')
            if time.monotonic()-started>wall_limit_seconds:raise TimeoutError('job wall limit exceeded')
            if shutil.disk_usage(root).free<12*1024**3:(root/'coordinator/pause.request').touch()
            time.sleep(1)
        if coordinator.returncode:raise RuntimeError('coordinator aborted; inspect its log and private inflight markers')
        receipt=json.loads((root/'coordinator/verification.json').read_text())
        receipt['supervisor_wall_seconds']=time.monotonic()-started
        return receipt
    finally:
        for process in [*children,*([coordinator] if coordinator else [])]:
            if process.poll() is None:process.terminate()
        for process in [*children,*([coordinator] if coordinator else [])]:
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait()

def export_and_prune(root,destination,work_root,receipt,*,prune=True):
    """Only own new completed job directories, after durable evidence verification."""
    from independent_clients.common import atomic_json
    import hashlib
    root=Path(root).resolve();destination=Path(destination).resolve();work_root=Path(work_root).resolve()
    if root.parent!=work_root or root==work_root or not (root/'.experiment-pack-owned').is_file():raise RuntimeError('refusing unsafe cleanup path')
    job=json.loads((root/'public_job.json').read_text())
    if (root/'.experiment-pack-owned').read_text()!=job['job_id'] or receipt['status']!='completed' or receipt['job_id']!=job['job_id']:raise RuntimeError('unverified completion; never prune')
    journal=json.loads((root/'coordinator/journal.json').read_text())
    if (receipt['completed_rounds']!=job['config']['rounds'] or
        [r['round'] for r in receipt['records']]!=list(range(1,job['config']['rounds']+1)) or
        journal['job_id']!=job['job_id'] or journal['completed']!=receipt['completed_rounds'] or journal['records']!=receipt['records'] or journal.get('pending')):
        raise RuntimeError('incomplete/mismatched durable journal; never prune')
    if destination==root or root in destination.parents:raise RuntimeError('archive must be outside private workspace')
    prior=destination/'public_job.json'
    if prior.exists() and json.loads(prior.read_text())['job_id']!=job['job_id']:raise RuntimeError('archive belongs to another job; never overwrite or prune')
    destination.mkdir(parents=True,exist_ok=True)
    atomic_json(destination/'verification.json',receipt);atomic_json(destination/'public_job.json',job)
    for name in ['journal.json','rpc_audit.json']:
        path=root/'coordinator'/name
        if path.exists():
            temporary=destination/(name+'.tmp')
            with path.open('rb') as source,temporary.open('wb') as target:
                shutil.copyfileobj(source,target);target.flush();os.fsync(target.fileno())
            os.replace(temporary,destination/name)
    names=['verification.json','public_job.json','journal.json']
    if (destination/'rpc_audit.json').exists():names.append('rpc_audit.json')
    checks={name:hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in names}
    atomic_json(destination/'checksums.json',checks)
    for name,value in checks.items():
        if hashlib.sha256((destination/name).read_bytes()).hexdigest()!=value:raise RuntimeError('archive verification failed')
    from .controller import verify_completed
    if not verify_completed(destination,job['config']['declared_config_sha256']):raise RuntimeError('archive semantic verification failed; never prune')
    descriptor=os.open(destination,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    if prune:
        # Contains only this controller's fresh job artifacts. Official shared
        # data cache and all historical project directories are outside root.
        shutil.rmtree(root)
