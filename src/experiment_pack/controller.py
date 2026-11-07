"""Serial, gated experiment controller. Importing/building never starts jobs."""
import hashlib,json,os,platform,shutil,subprocess,sys,time
from pathlib import Path
from .manifest import build,validate,digest
from .runtime import source_hash,source_files

def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8') as stream:
        if isinstance(value,dict) and 'jobs' in value and 'unique_jobs' in value:
            header={k:v for k,v in value.items() if k!='jobs'}
            stream.write(json.dumps(header,indent=2)[:-2]+',\n"jobs":[\n')
            stream.write(',\n'.join(json.dumps(j,separators=(',',':')) for j in value['jobs']));stream.write('\n]}\n')
        else:json.dump(value,stream,indent=2);stream.write('\n')
        stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,path)

def build_pack(directory):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    manifest=build();validate(manifest)
    files={'manifest.json':manifest,'source_snapshot.json':dict(hash=source_hash(),files=source_files())}
    for name,value in files.items():
        path=directory/name
        if path.exists() and json.loads(path.read_text())!=value:raise RuntimeError('existing pack differs; build into a new directory')
        dump(path,value)
    if not (directory/'state.json').exists():dump(directory/'state.json',dict(status='prepared_not_started',completed=[],failed=[],current=None,GPU_validated=False))
    return manifest

def gpu_preflight():
    result=dict(platform=platform.platform(),python=platform.python_version(),linux=sys.platform=='linux',GPU_available=False)
    if sys.platform!='linux':result['blocked_reason']='Linux Landlock/seccomp required';return result
    code="import torch,json; assert torch.cuda.is_available(),'CUDA unavailable'; x=torch.ones((16,16),device='cuda'); y=x@x;torch.cuda.synchronize(); print(json.dumps(dict(device=torch.cuda.get_device_name(0),memory=torch.cuda.get_device_properties(0).total_memory,torch=str(torch.__version__),cuda=torch.version.cuda)))"
    p=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    result['GPU_available']=p.returncode==0
    if p.returncode:result['blocked_reason']=p.stderr[-1500:]
    else:result['GPU']=json.loads(p.stdout)
    result['free_disk_GiB']=shutil.disk_usage(Path.cwd()).free/1024**3
    import ctypes
    libc=ctypes.CDLL(None);result['landlock_abi']=libc.syscall(444,0,0,1)
    import importlib.metadata
    result['packages']={n:importlib.metadata.version(n) for n in ['torch','torchvision','numpy','networkx','cryptography','rbcl','Pillow','cffi','pycparser']}
    from secure_protocol_v6.rangeproof import info
    result['native_binary_sha256']=info()['binary_sha256']
    if result['GPU_available']:
        smi=subprocess.run(['nvidia-smi','--query-gpu=driver_version','--format=csv,noheader'],capture_output=True,text=True)
        result['driver']=smi.stdout.strip()
    return result

def freeze_data(pack,cache):
    pack=Path(pack);cache=Path(cache);sources={}
    for name in ('mnist','fashion_mnist','cifar10'):
        receipt=json.loads((cache/name/'receipt.json').read_text())
        for filename,value in receipt['sha256'].items():
            if hashlib.sha256((cache/name/filename).read_bytes()).hexdigest()!=value:raise RuntimeError('data cache checksum mismatch')
        sources[name]=receipt
    snapshot=dict(datasets=sources);snapshot['sha256']=digest(snapshot)
    path=pack/'data_snapshot.json'
    if path.exists() and json.loads(path.read_text())!=snapshot:raise RuntimeError('frozen data changed; build new pack')
    dump(path,snapshot);state=json.loads((pack/'state.json').read_text());state['data_ready']=True;dump(pack/'state.json',state)
    return snapshot

def verify_completed(folder,declared_sha):
    folder=Path(folder)
    try:
        receipt=json.loads((folder/'verification.json').read_text());job=json.loads((folder/'public_job.json').read_text());checks=json.loads((folder/'checksums.json').read_text())
        if receipt['status']!='completed' or receipt['job_id']!=job['job_id'] or job['config']['declared_config_sha256']!=declared_sha or receipt['completed_rounds']!=job['config']['rounds']:return False
        if not {'verification.json','public_job.json','journal.json'}<=set(checks):return False
        if [r['round'] for r in receipt['records']]!=list(range(1,job['config']['rounds']+1)):return False
        return all(hashlib.sha256((folder/name).read_bytes()).hexdigest()==value for name,value in checks.items())
    except (OSError,ValueError,KeyError):return False

def select_rates(pack,manifest):
    selected={}
    for dataset in ('mnist','fashion_mnist','cifar10'):
        for model in ('mlp','cnn'):
            candidates=[]
            for lr in (.0003,.001,.003):
                scores=[];sources=[]
                for split in ('iid','non_iid'):
                    matches=[j for j in manifest['jobs'] if j['config']['workflow']=='tuning' and j['config']['dataset']==dataset and j['config']['model']==model and j['config']['learning_rate']==lr and j['config']['split']==split]
                    j=matches[0];folder=Path(pack)/'results'/j['id']
                    if not verify_completed(folder,j['config_sha256']):break
                    receipt=json.loads((folder/'verification.json').read_text())
                    scores.append(max(r['metrics']['validation_accuracy'] for r in receipt['records'] if r['metrics']['validation_accuracy'] is not None));sources.append(j['id'])
                if len(scores)==2:candidates.append((sum(scores)/2,lr,sources))
            if len(candidates)==3:
                best=sorted(candidates,key=lambda x:(-x[0],x[1]))[0]
                selected[f'{dataset}/{model}']=dict(learning_rate=best[1],validation_score=best[0],source_jobs=best[2],test_used=False)
    value=dict(selection=selected,rule='mean best scheduled validation accuracy across IID/shards; tie smallerLR; seed7 only')
    value['selection_sha256']=digest(value);return value

def execute(pack,work_root,data_cache,*,until='gpu_gate',max_estimated_hours=168,retain_private=False):
    pack=Path(pack).resolve();work_root=Path(work_root).resolve();data_cache=Path(data_cache).resolve()
    manifest=json.loads((pack/'manifest.json').read_text());validate(manifest)
    snapshot=json.loads((pack/'source_snapshot.json').read_text())
    if snapshot['hash']!=source_hash():raise RuntimeError('source differs from frozen pack; build a new package')
    if sys.platform!='linux':raise RuntimeError('execution is Linux only')
    from independent_clients.common import run_lock
    from .provision import provision
    from .launch import launch,export_and_prune
    stages=['gpu_gate','smoke','tuning','validation','sensitivity','network'];allowed=set(stages[:stages.index(until)+1])
    work_root.mkdir(parents=True,exist_ok=True)
    with run_lock(pack/'controller.lock'):
        check=gpu_preflight();dump(pack/'preflight.json',check)
        if not check['GPU_available'] or check.get('landlock_abi',0)<4:raise RuntimeError('GPU/kernel preflight blocked; no job started')
        if check['GPU']['memory']<20*1024**3:raise RuntimeError('GPU memory profile below20GiB; no job started')
        frozen=json.loads((pack/'data_snapshot.json').read_text())
        if digest({'datasets':frozen['datasets']})!=frozen['sha256']:raise RuntimeError('data snapshot hash mismatch')
        for name,receipt in frozen['datasets'].items():
            if json.loads((data_cache/name/'receipt.json').read_text())!=receipt:raise RuntimeError('dataset provenance differs from frozen pack')
        profile={k:v for k,v in check.items() if k not in ('free_disk_GiB',)}
        profile_sha=digest(profile)
        if (pack/'runtime_profile.json').exists():
            if json.loads((pack/'runtime_profile.json').read_text())['sha256']!=profile_sha:raise RuntimeError('runtime changed since calibration; do not mix environments')
        else:dump(pack/'runtime_profile.json',dict(sha256=profile_sha,profile=profile))
        state=json.loads((pack/'state.json').read_text());completed=set(state['completed'])
        if state.get('archive_review_required'):raise RuntimeError('archive recovery requires operator review; no jobs started')
        for job in manifest['jobs']:
            archived=pack/'results'/job['id']
            if verify_completed(archived,job['config_sha256']):completed.add(job['id'])
            elif job['id'] in completed:
                state.update(status='blocked_archive_requires_review',current=None,archive_review_required=[job['id']]);dump(pack/'state.json',state)
                raise RuntimeError('recorded completion has missing/invalid archive; never retrain automatically')
        for record in manifest['jobs']:
            destination=pack/'results'/record['id']
            cfg=record['config']
            if record['id'] in completed or cfg['workflow'] not in allowed:continue
            if not set(record['depends_on'])<=completed:raise RuntimeError('upstream gate/tuning not complete')
            if (pack/'pause.request').exists():break
            if shutil.disk_usage(work_root).free<20*1024**3:raise RuntimeError('free disk below20GiB; no new job started')
            mem={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')}
            if mem['MemAvailable']<48*1024**2:raise RuntimeError('available RAM below48GiB; no new50-client job started')
            effective=dict(cfg,declared_config_sha256=record['config_sha256'])
            if effective['learning_rate'] is None:
                selection=select_rates(pack,manifest);dump(pack/'learning_rate_selection.json',selection)
                key=effective['learning_rate_ref']
                if key not in selection['selection']:raise RuntimeError('validation-only LR selection incomplete')
                effective['learning_rate']=selection['selection'][key]['learning_rate'];effective['selection_sha256']=selection['selection_sha256']
            # A conservative calibration budget guard, never an unsupported ETA.
            if cfg['workflow']!='gpu_gate':
                gate_records=[]
                for j in manifest['jobs']:
                    if j['config']['workflow']=='gpu_gate':
                        p=pack/'results'/j['id']/'verification.json'
                        if p.exists():gate_records+=json.loads(p.read_text())['records']
                if not gate_records:raise RuntimeError('calibration missing')
                upper_round=max(r['seconds'] for r in gate_records)*4
                pending_rounds=sum(j['config']['rounds'] for j in manifest['jobs'] if j['id'] not in completed and j['config']['workflow'] in allowed)
                forecast=dict(rough_upper_hours=upper_round*pending_rounds/3600,method='4x worst measured dense GPU-gate round; scheduling guard, not performance estimate')
                dump(pack/'calibration_budget.json',forecast)
                if forecast['rough_upper_hours']>max_estimated_hours:raise RuntimeError('measured calibration exceeds configured campaign budget; bulk jobs remain pending')
            workspace=work_root/record['id']
            if not workspace.exists():
                source=data_cache/cfg['dataset']
                if not (source/'receipt.json').exists():raise RuntimeError('prepare official dataset cache before execution')
                provision(workspace,effective,source)
            else:
                existing=json.loads((workspace/'public_job.json').read_text())
                if existing['config']!=effective or existing['source_hash']!=source_hash():raise RuntimeError('existing private job/config mismatch')
            state.update(status='running',current=record['id'],completed=sorted(completed));dump(pack/'state.json',state)
            try:
                receipt=launch(workspace)
                if receipt['status']=='completed':
                    receipt['runtime_profile_sha256']=profile_sha
                    export_and_prune(workspace,destination,work_root,receipt,prune=not retain_private)
                    if not verify_completed(destination,record['config_sha256']):raise RuntimeError('completed receipt verification failed')
            except BaseException:
                state.update(status='blocked_job_requires_review',current=record['id']);state['failed']=sorted(set(state['failed'])|{record['id']});dump(pack/'state.json',state);raise
            if receipt['status']!='completed':state.update(status='paused',current=record['id']);dump(pack/'state.json',state);return state
            completed.add(record['id']);state.update(completed=sorted(completed),current=None,status='between_jobs',GPU_validated=all(j['id'] in completed for j in manifest['jobs'] if j['config']['workflow']=='gpu_gate'));dump(pack/'state.json',state)
        state.update(status='completed' if len(completed)==manifest['unique_jobs'] else 'stage_complete_or_paused',completed=sorted(completed),current=None);dump(pack/'state.json',state)
        return state
