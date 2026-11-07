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
def configuration(model,dataset,split,mode,seed,topology='ring',alpha=None,ratio=.4,stage='validation'):
    return dict(model=model,dataset=dataset,clients=50,seed=seed,mode=mode,split=split,alpha=alpha,
        topology=topology,caveman_cliques=2,barabasi_m=2,shards_per_client=2,dirichlet_min_samples=10,
        rounds=2 if stage=='calibration' else 20,local_epochs=1,batch_size=128,learning_rate=.001,
        optimizer='AdamW',weight_decay=.01,warmup_rounds=3,schedule_rounds=20,validation_every=5,
        HE_ratio=ratio,HE_policy='legacy_update_norm_topk',CKKS=dict(poly_modulus_degree=8192,coeff_mod_bit_sizes=[60,40,40,60],scale_bits=40,threads=1),
        normalization='training_fold_only',data_fold_seed=20261106,augmentation='cifar_random_crop_flip_only',
        stage=stage,threat_model='trusted_single_process_simulation',communication='calculated_payload_bytes_not_measured_network')
def build():
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
    value['sha256']=digest(value);return value
def validate(manifest):
    if digest({k:v for k,v in manifest.items() if k!='sha256'})!=manifest['sha256']:raise ValueError('manifest hash mismatch')
    seen=set()
    for b in manifest['bundles']:
        group={}
        for j in b['jobs']:
            c=j['config'];key=(c['model'],c['mode']);group.setdefault(key,set()).add(c['seed'])
            if j['id'] in seen or digest(c)!=j['config_sha256'] or c['clients']!=50:raise ValueError('invalid job')
            seen.add(j['id'])
        if any(seeds!={1,2,3} for seeds in group.values()) or {k[0] for k in group}!=set(MODELS):raise ValueError('incomplete comparison bundle')
    if len(seen)!=manifest['candidate_jobs']:raise ValueError('job count mismatch')
    return manifest
def prepare(path):
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    for name,value in [('manifest.json',build()),('source_snapshot.json',source_snapshot())]:
        file=path/name
        if file.exists() and json.loads(file.read_text())!=value:raise RuntimeError('existing frozen pack differs; use a new directory')
        atomic(file,value)
    if not (path/'state.json').exists():atomic(path/'state.json',dict(status='prepared_not_started',completed=[],started_UTC=None,deadline_UTC=None))
    return json.loads((path/'manifest.json').read_text())
