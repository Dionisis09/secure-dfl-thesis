import hashlib,itertools,json,os,tempfile
from pathlib import Path

DATASETS=('cifar10','mnist','fashion_mnist')
MODELS=('cnn','mlp')
MODES=('none','masking','pairwise_masking','selective_he','adaptive_hybrid')
TOPOLOGIES=('ring','caveman','barabasi_albert','fully_connected')

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False,encoding='utf-8',newline='\n') as f:
        name=f.name;json.dump(value,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(name,path)
def source_snapshot():
    root=Path(__file__).resolve().parents[2]
    files=list((root/'src/simulator_pack').glob('*.py'))+[root/'scripts/simulator50.py',root/'requirements-simulator50.txt']
    files += [root/'src'/n for n in ['adaptive.py','aggregation.py','masking.py','he_utils.py','client.py','matched_models.py','data_utils.py','topology.py']]
    hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest() for p in sorted(files)}
    return dict(hash=digest(hashes),files=hashes)
def configuration(model,dataset,split,mode,seed,topology='ring',alpha=None,ratio=.4,stage='validation',clients=50):
    return dict(model=model,dataset=dataset,clients=clients,seed=seed,mode=mode,split=split,alpha=alpha,
        topology=topology,caveman_cliques=2,barabasi_m=2,shards_per_client=2,dirichlet_min_samples=10,
        rounds=2 if stage=='calibration' else 20,local_epochs=1,batch_size=128,learning_rate=.001,
        optimizer='AdamW',weight_decay=.01,warmup_rounds=3,schedule_rounds=20,validation_every=5,
        HE_ratio=ratio,HE_policy='legacy_update_norm_topk',CKKS=dict(poly_modulus_degree=8192,coeff_mod_bit_sizes=[60,40,40,60],scale_bits=40,threads=1),
        normalization='training_fold_only',data_fold_seed=20261106,augmentation='cifar_random_crop_flip_only',
        stage=stage,threat_model='trusted_single_process_simulation',communication='calculated_payload_bytes_not_measured_network')
def build(scaling4090=False):
    bundles=[]
    def bundle(dataset,split,alpha=None,topology='ring',ratio=.4,modes=MODES):
        jobs=[]
        for model,mode,seed in itertools.product(MODELS,modes,(1,2,3)):
            c=configuration(model,dataset,split,mode,seed,topology,alpha,ratio,'sensitivity' if ratio!=.4 else 'validation')
            jobs.append(dict(id='sim-'+digest(c)[:24],config=c,config_sha256=digest(c)))
        bundles.append(dict(id='bundle-'+digest([j['id'] for j in jobs])[:20],priority=len(bundles),jobs=jobs))
    for dataset in DATASETS:
        for split,alpha in [('iid',None),('non_iid',None),('dirichlet',.5)]:bundle(dataset,split,alpha)
    for topology in TOPOLOGIES[1:]:bundle('cifar10','dirichlet',.5,topology)
    for alpha in (.1,1.):bundle('cifar10','dirichlet',alpha)
    for split,alpha,ratio in itertools.product(('iid','dirichlet'),(.5,),(.2,.6,.8,1.)):
        bundle('cifar10',split,alpha if split=='dirichlet' else None,ratio=ratio,modes=('adaptive_hybrid',))
    value=dict(format=1,style='legacy_trusted_simulator_matched_models',clients=50,seeds=[1,2,3],rounds=20,
        candidate_jobs=sum(len(b['jobs']) for b in bundles),bundles=bundles,
        sensitivity_reference_jobs=[j['id'] for b in bundles for j in b['jobs'] if j['config']['dataset']=='cifar10' and j['config']['topology']=='ring' and j['config']['mode']=='adaptive_hybrid' and (j['config']['split'],j['config']['alpha']) in [('iid',None),('dirichlet',.5)] and j['config']['HE_ratio']==.4],
        policy=dict(auto_start=False,hard_wall_hours=120,planned_compute_hours=96,reserve_hours=24,
            benchmark_seed=0,all_results_require_three_seeds=True,whole_paired_model_bundles_only=True,
            no_training_replay_substitution=True,no_silent_CPU_fallback=True,no_test_driven_selection=True,
            historical_results_read_only=True,HE_is_real_CKKS=True,trainer_can_read_models_and_keys=True))
    if scaling4090:
        references=[j['id'] for b in bundles for j in b['jobs'] if j['config']['dataset']=='cifar10' and j['config']['topology']=='ring' and j['config']['split']=='dirichlet' and j['config']['alpha']==.5 and j['config']['mode'] in ('none','adaptive_hybrid') and j['config']['HE_ratio']==.4]
        jobs=[]
        for clients,model,mode,seed in itertools.product((20,100),MODELS,('none','adaptive_hybrid'),(1,2,3)):
            cfg=configuration(model,'cifar10','dirichlet',mode,seed,alpha=.5,stage='scaling',clients=clients)
            jobs.append(dict(id='sim-'+digest(cfg)[:24],config=cfg,config_sha256=digest(cfg)))
        extra=dict(id='bundle-'+digest([j['id'] for j in jobs])[:20],jobs=jobs)
        bundles.insert(3,extra)
        for priority,b in enumerate(bundles):b['priority']=priority
        value.update(format=2,style='trusted_simulator_scaling4090',clients=[20,50,100],base_clients=50,candidate_jobs=492,
            scaling=dict(client_counts=[20,50,100],dataset='cifar10',split='dirichlet',alpha=.5,topology='ring',models=list(MODELS),modes=['none','adaptive_hybrid'],seeds=[1,2,3],
                total_comparison_cases=36,new_job_ids=[j['id'] for j in jobs],reference_50_job_ids=references))
        value['policy'].update(target_GPU_family='RTX 4090',minimum_GPU_memory_bytes=20*1024**3,
            required_bundle_ids=[b['id'] for b in bundles[:4]],scaling_is_required=True,
            calibration_client_counts=[20,50,100],fresh_server_calibration_required=True,
            clock_must_be_inherited=True,clock_restart_on_migration=False)
    value['sha256']=digest(value);return value
def validate(manifest):
    if digest({k:v for k,v in manifest.items() if k!='sha256'})!=manifest['sha256']:raise ValueError('manifest hash mismatch')
    seen=set()
    for b in manifest['bundles']:
        group={}
        for j in b['jobs']:
            c=j['config'];key=(c['clients'],c['model'],c['mode']);group.setdefault(key,set()).add(c['seed'])
            permitted=c['clients']==50 or (manifest.get('scaling') and c['stage']=='scaling' and c['clients'] in (20,100))
            if j['id'] in seen or digest(c)!=j['config_sha256'] or j['id']!='sim-'+digest(c)[:24] or not permitted:raise ValueError('invalid job')
            seen.add(j['id'])
        if any(seeds!={1,2,3} for seeds in group.values()) or {k[1] for k in group}!=set(MODELS):raise ValueError('incomplete comparison bundle')
    if len(seen)!=manifest['candidate_jobs']:raise ValueError('job count mismatch')
    if manifest.get('scaling'):
        s=manifest['scaling'];lookup={j['id']:j['config'] for b in manifest['bundles'] for j in b['jobs']}
        expected={(n,m,mode,seed) for n,m,mode,seed in itertools.product((20,50,100),MODELS,('none','adaptive_hybrid'),(1,2,3))}
        rows=s['new_job_ids']+s['reference_50_job_ids']
        if len(s['new_job_ids'])!=24 or len(s['reference_50_job_ids'])!=12 or len(set(rows))!=36 or not set(rows)<=seen:raise ValueError('scaling references invalid')
        actual=set()
        for identifier in rows:
            c=lookup[identifier];actual.add((c['clients'],c['model'],c['mode'],c['seed']))
            if (c['dataset'],c['split'],c['alpha'],c['topology'],c['HE_ratio'])!=('cifar10','dirichlet',.5,'ring',.4):raise ValueError('scaling setting mismatch')
        if actual!=expected:raise ValueError('scaling grid incomplete')
        if not set(manifest['policy']['required_bundle_ids'])<={b['id'] for b in manifest['bundles']}:raise ValueError('required bundle missing')
    return manifest
def prepare(path,scaling4090=False,clock_from=None):
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    inherited=None
    if scaling4090:
        if clock_from is None:raise ValueError('4090 pack requires the existing campaign clock; no automatic new120h window')
        inherited=json.loads(Path(clock_from).read_text())
        import datetime
        start=datetime.datetime.fromisoformat(inherited['started_UTC']).timestamp();end=datetime.datetime.fromisoformat(inherited['deadline_UTC']).timestamp()
        if not 0<end-start<=120*3600:raise ValueError('invalid inherited120h clock')
    manifest=validate(build(scaling4090))
    for name,value in [('manifest.json',manifest),('source_snapshot.json',source_snapshot())]:
        file=path/name
        if file.exists() and json.loads(file.read_text())!=value:raise RuntimeError('existing frozen pack differs; use a new directory')
        atomic(file,value)
    state_path=path/'state.json'
    if state_path.exists() and inherited:
        state=json.loads(state_path.read_text())
        if (state['started_UTC'],state['deadline_UTC'])!=(inherited['started_UTC'],inherited['deadline_UTC']):raise RuntimeError('existing clock differs; never overwrite/extend it')
    if not state_path.exists():
        state=dict(status='prepared_requires_server_calibration' if scaling4090 else 'prepared_not_started',completed=[],started_UTC=None,deadline_UTC=None)
        if inherited:state.update(started_UTC=inherited['started_UTC'],deadline_UTC=inherited['deadline_UTC'],clock_inherited=True)
        atomic(state_path,state)
    return json.loads((path/'manifest.json').read_text())
