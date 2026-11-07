"""Explicit calibration, measured bundle admission, and a fixed 120-hour clock."""
import contextlib,datetime,json,math,os,shutil,subprocess,sys,time
from pathlib import Path
from .design import atomic,digest,validate,source_snapshot,MODELS,MODES,configuration

@contextlib.contextmanager
def lock(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as f:
        f.seek(0);f.write(b'0');f.flush();f.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            f.seek(0)
            if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)
def check_source(pack):
    value=json.loads((Path(pack)/'source_snapshot.json').read_text())
    if value!=source_snapshot():raise RuntimeError('frozen source differs; use a new pack')
def check_data(pack,cache):
    frozen=json.loads((Path(pack)/'data_snapshot.json').read_text())
    if digest(frozen['datasets'])!=frozen['sha256']:raise RuntimeError('data snapshot invalid')
    for n,receipt in frozen['datasets'].items():
        if json.loads((Path(cache)/n/'receipt.json').read_text())!=receipt:raise RuntimeError('cache differs from frozen data')
def utc(epoch):return datetime.datetime.fromtimestamp(epoch,datetime.timezone.utc).isoformat()
def require_target(manifest,profile):
    """The scaling pack must be calibrated/run on its actual target, not the laptop."""
    if not manifest.get('scaling'):return
    import re
    if profile.get('device')!='cuda' or not re.search(r'RTX\s*4090\b',profile.get('GPU') or '',re.I) or profile.get('GPU_memory_bytes',0)<manifest['policy']['minimum_GPU_memory_bytes']:
        raise RuntimeError('requires RTX4090 family with at least20GiB VRAM; no laptop/CPU timing substitution')

def calibration_configs(manifest,topologies):
    scaling=bool(manifest.get('scaling'))
    for topology in topologies:
        for model in MODELS:
            for mode in MODES:
                yield configuration(model,'cifar10','dirichlet' if scaling else 'iid',mode,0,topology,alpha=.5 if scaling else None,stage='calibration')
    if scaling:
        for clients in (20,100):
            for model in MODELS:
                for mode in ('none','adaptive_hybrid'):
                    yield configuration(model,'cifar10','dirichlet',mode,0,alpha=.5,stage='calibration',clients=clients)

def calibration_key(cfg):return (cfg['model'],cfg['mode'],cfg['topology'],cfg['clients'])

def clock(pack):
    pack=Path(pack);state=json.loads((pack/'state.json').read_text())
    if state['started_UTC'] is None:
        manifest=json.loads((pack/'manifest.json').read_text())
        if manifest['policy'].get('clock_must_be_inherited'):raise RuntimeError('missing inherited clock; never restart the120h window')
        now=time.time();state.update(started_UTC=utc(now),deadline_UTC=utc(now+120*3600));atomic(pack/'state.json',state)
    return datetime.datetime.fromisoformat(state['deadline_UTC']).timestamp()
def child(pack,job,cache,device,deadline):
    pack=Path(pack);folder=pack/('calibration' if job['config']['stage']=='calibration' else 'results')/job['id'];folder.mkdir(parents=True,exist_ok=True)
    atomic(folder/'request.json',job['config']);root=Path(__file__).resolve().parents[2]
    argv=[sys.executable,'-u',str(root/'scripts/simulator50.py'),'_job','--config',str(folder/'request.json'),'--output',str(folder),'--cache',str(Path(cache).resolve()),'--device',device,'--deadline',str(deadline)]
    with (folder/'runner.log').open('ab') as log:
        p=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            while p.poll() is None:
                if time.time()>=deadline:
                    p.terminate()
                    try:p.wait(timeout=5)
                    except subprocess.TimeoutExpired:p.kill();p.wait(timeout=10)
                    raise TimeoutError('120-hour deadline reached; last atomic checkpoint retained')
                if shutil.disk_usage(pack).free<12*1024**3:(folder/'pause.request').touch()
                if (pack/'pause.request').exists():(folder/'pause.request').touch()
                time.sleep(1)
            if p.returncode:raise RuntimeError('job failed; checkpoint retained; inspect '+str(folder/'runner.log'))
        finally:
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait(timeout=10)
    return folder
def calibrate(pack,cache,topologies=('ring',)):
    from .engine import completed,runtime
    pack=Path(pack).resolve();check_source(pack);check_data(pack,cache)
    manifest=validate(json.loads((pack/'manifest.json').read_text()))
    if not __import__('torch').cuda.is_available():raise RuntimeError('CUDA unavailable; no calibration started')
    profile=runtime('cuda');require_target(manifest,profile);profile_hash=digest(profile)
    data=json.loads((pack/'data_snapshot.json').read_text())['datasets']['cifar10']['receipt_sha256']
    with lock(pack/'controller.lock'):
        deadline=min(clock(pack),time.time()+3600)
        for cfg in calibration_configs(manifest,topologies):
            job=dict(id='cal-'+digest(cfg)[:24],config=cfg);folder=pack/'calibration'/job['id']
            if completed(folder,cfg,source_snapshot()['hash'],profile_hash,data):continue
            if (folder/'complete.json').exists():raise RuntimeError('invalid completed calibration; no automatic retraining')
            if time.time()>=deadline or (pack/'pause.request').exists():return
            state=json.loads((pack/'state.json').read_text());state.update(status='calibrating',current=job['id']);atomic(pack/'state.json',state)
            try:result=child(pack,job,cache,'cuda',deadline)
            except BaseException:
                state.update(status='stopped_error_or_deadline',current=job['id']);atomic(pack/'state.json',state);raise
            if not completed(result,cfg,source_snapshot()['hash'],profile_hash,data):
                state.update(status='paused_or_deadline_reached');atomic(pack/'state.json',state);return
        state=json.loads((pack/'state.json').read_text());state.update(status='calibration_stage_finished',current=None);atomic(pack/'state.json',state)
def predicted_seconds(receipt,records,dataset):
    if len(records)!=2 or not all(r['timing_complete'] for r in records):raise RuntimeError('incomplete calibration timings')
    mean=lambda key:sum(r[key] for r in records)/len(records)
    val=[r['validation_seconds'] for r in records if r['validation'] is not None]
    factor=1. if dataset=='cifar10' else 1.5
    # Conservative admission model, not a guaranteed wall-time prediction.
    return 2*factor*(receipt['setup_seconds']+20*sum(mean(n) for n in ['training_seconds','aggregation_seconds','snapshot_seconds','load_seconds','checkpoint_seconds'])+4*sum(val)/len(val)+receipt['test_final_seconds']+receipt['test_best_seconds'])
def plan(pack):
    from .engine import completed,runtime
    pack=Path(pack);check_source(pack);manifest=validate(json.loads((pack/'manifest.json').read_text()));samples={};profiles=set()
    if manifest.get('scaling'):
        frozen_snapshot=json.loads((pack/'data_snapshot.json').read_text())
        if digest(frozen_snapshot['datasets'])!=frozen_snapshot['sha256']:raise RuntimeError('data snapshot invalid')
    if (pack/'selected_plan.json').exists():
        value=json.loads((pack/'selected_plan.json').read_text())
        if value['sha256']!=digest({k:v for k,v in value.items() if k!='sha256'}) or value['manifest_sha256']!=manifest['sha256']:raise RuntimeError('selected plan hash mismatch')
        return value
    for folder in sorted((pack/'calibration').glob('cal-*')):
        if not completed(folder):continue
        r=json.loads((folder/'complete.json').read_text());cfg=r['config']
        if r['source_hash']!=source_snapshot()['hash']:raise RuntimeError('calibration source differs')
        if manifest.get('scaling'):
            require_target(manifest,r['runtime_profile'])
            frozen=json.loads((pack/'data_snapshot.json').read_text())['datasets']['cifar10']['receipt_sha256']
            if r['runtime_sha256']!=digest(r['runtime_profile']) or r['data_receipt_sha256']!=frozen:raise RuntimeError('calibration runtime/data provenance differs')
            expected=configuration(cfg['model'],'cifar10','dirichlet',cfg['mode'],0,cfg['topology'],alpha=.5,stage='calibration',clients=cfg['clients'])
            if cfg!=expected:raise RuntimeError('calibration settings differ')
        key=calibration_key(cfg)
        if key in samples:raise RuntimeError('duplicate calibration profile')
        samples[key]=(r,json.loads((folder/'metrics.json').read_text()));profiles.add(r['runtime_sha256'])
    if len(profiles)!=1:raise RuntimeError('require calibration from exactly one recorded runtime')
    state=json.loads((pack/'state.json').read_text())
    available=min(96*3600,datetime.datetime.fromisoformat(state['deadline_UTC']).timestamp()-time.time()-24*3600)
    selected=[];excluded=[];total=0.
    for b in manifest['bundles']:
        keys={calibration_key(j['config']) for j in b['jobs']}
        if not keys<=samples.keys():excluded.append(dict(bundle=b['id'],reason='topology/mode calibration missing'));continue
        cost=sum(predicted_seconds(*samples[calibration_key(j['config'])],j['config']['dataset']) for j in b['jobs'])
        if total+cost>available:excluded.append(dict(bundle=b['id'],reason='does not fit conservative budget',estimated_seconds=cost));continue
        selected.append(dict(bundle=b['id'],job_ids=[j['id'] for j in b['jobs']],estimated_seconds=cost,
            job_estimated_seconds={j['id']:predicted_seconds(*samples[calibration_key(j['config'])],j['config']['dataset']) for j in b['jobs']}));total+=cost
    core=set(manifest['policy'].get('required_bundle_ids',[b['id'] for b in manifest['bundles'][:3]]))
    value=dict(status='ready' if core<={b['bundle'] for b in selected} else 'insufficient_budget_for_primary_comparison',selected=selected,excluded=excluded,
        estimated_seconds=total,deadline_UTC=state['deadline_UTC'],runtime_sha256=next(iter(profiles)),manifest_sha256=manifest['sha256'],
        required_bundle_ids=sorted(core),scaling_cases=manifest.get('scaling',{}).get('total_comparison_cases',0),
        assumptions='2x measured CIFAR stage costs; grayscale1.5x CIFAR; client-count-specific calibration; no accuracy/test-based selection; optional graphs require their own calibration')
    value['sha256']=digest(value)
    old=pack/'selected_plan.json'
    if old.exists() and json.loads(old.read_text())!=value:raise RuntimeError('selection already frozen; preserve it rather than silently replace')
    atomic(old if value['status']=='ready' else pack/'admission_blocked.json',value);return value
def run(pack,cache):
    from .engine import completed,runtime
    pack=Path(pack).resolve();check_source(pack);check_data(pack,cache);selection=json.loads((pack/'selected_plan.json').read_text());manifest=validate(json.loads((pack/'manifest.json').read_text()))
    if selection['sha256']!=digest({k:v for k,v in selection.items() if k!='sha256'}) or selection['manifest_sha256']!=manifest['sha256'] or selection['status']!='ready':raise RuntimeError('selected plan invalid/not admitted')
    profile=runtime('cuda');require_target(manifest,profile)
    if digest(profile)!=selection['runtime_sha256']:raise RuntimeError('runtime differs from calibration; no mixed timing profile')
    frozen=json.loads((pack/'data_snapshot.json').read_text())['datasets']
    jobs={j['id']:j for b in manifest['bundles'] for j in b['jobs']}
    with lock(pack/'controller.lock'):
        deadline=clock(pack)
        for b in selection['selected']:
            pending=[i for i in b['job_ids'] if not completed(pack/'results'/i,jobs[i]['config'],source_snapshot()['hash'],selection['runtime_sha256'],frozen[jobs[i]['config']['dataset']]['receipt_sha256'])]
            remaining=sum(b.get('job_estimated_seconds',{}).get(i,b['estimated_seconds']/len(b['job_ids'])) for i in pending)
            if time.time()+remaining>deadline-3600 or (pack/'pause.request').exists():break
            for identifier in b['job_ids']:
                job=jobs[identifier];folder=pack/'results'/identifier
                expected_data=frozen[job['config']['dataset']]['receipt_sha256']
                if completed(folder,job['config'],source_snapshot()['hash'],selection['runtime_sha256'],expected_data):continue
                if (folder/'complete.json').exists():raise RuntimeError('completed archive invalid; no automatic retraining')
                if time.time()>=deadline or (pack/'pause.request').exists():break
                if shutil.disk_usage(pack).free<16*1024**3:raise RuntimeError('free disk below16GiB; no new job started')
                state=json.loads((pack/'state.json').read_text());state.update(status='running',current=identifier);atomic(pack/'state.json',state)
                try:result=child(pack,job,cache,'cuda',deadline)
                except BaseException:
                    state.update(status='stopped_error_or_deadline',current=identifier);atomic(pack/'state.json',state);raise
                if not completed(result,job['config'],source_snapshot()['hash'],selection['runtime_sha256'],expected_data):
                    state.update(status='paused_or_deadline_reached');atomic(pack/'state.json',state);return
        done=[i for b in selection['selected'] for i in b['job_ids'] if completed(pack/'results'/i,jobs[i]['config'],source_snapshot()['hash'],selection['runtime_sha256'],frozen[jobs[i]['config']['dataset']]['receipt_sha256'])]
        state=json.loads((pack/'state.json').read_text());state.update(status='selected_series_completed' if len(done)==sum(len(b['job_ids']) for b in selection['selected']) else 'paused_or_budget_exhausted',completed=done,current=None);atomic(pack/'state.json',state)
