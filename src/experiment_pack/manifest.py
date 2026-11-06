"""Declarative jobs; building a manifest never trains or launches a client."""
import hashlib
import itertools
import json
from pathlib import Path

DATASETS=('mnist','fashion_mnist','cifar10')
MODELS=('mlp','cnn')
TOPOLOGIES=('ring','fully_connected','caveman','barabasi_albert')
SPLITS=(('iid',None),('non_iid',None),('dirichlet',.1),('dirichlet',.5),('dirichlet',1.))
MODES=('none','masking','pairwise_masking','selective_he','hybrid_pairwise_head_he','adaptive_hybrid')
RATIOS=(.2,.4,.6,.8,1.)

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()

def config(model,dataset,split,alpha,topology,mode,seed,workflow='validation',ratio=.4,lr=None):
    return dict(version=8,model=model,dataset=dataset,split=split,dirichlet_alpha=alpha,
        topology=topology,caveman_cliques=2,barabasi_m=2,barabasi_initial_graph='complete_m_plus_one',mode=mode,seed=seed,clients=50,
        rounds=2 if workflow in ('network','gpu_gate','smoke') else 60,local_epochs=1,batch_size=128,
        optimizer='adamw',learning_rate=lr,learning_rate_ref=None if lr else f'{dataset}/{model}',
        weight_decay=.01,schedule='cosine_with_5_round_warmup',validation_every=5,
        requested_HE_ratio=ratio,adaptive_policy='graph_degree_topk_seeded_ties',
        scale=65536,head_bound=2.,backbone_bound=32.,aggregation='uniform_self_and_neighbors',
        baseline_precision='same_fixedpoint_as_protected_modes',
        metrics='secure_mean_client_validation_accuracy_and_loss',
        test_policy='never' if workflow=='tuning' else 'best_validation_checkpoint_and_last_round_only',
        data_fold_seed=20261106,validation_fraction=.1,dirichlet_min_samples=2 if workflow=='network' else 10,
        sample_budget=6400 if workflow=='gpu_gate' else 1500 if workflow in ('network','smoke') else None,
        evaluation_budget=500 if workflow in ('network','smoke','gpu_gate') else None,
        training_device='cuda',training_execution='serial_client_exec_workers',
        workflow=workflow)

def build():
    jobs=[]
    def add(cfg,deps=()):
        identifier=cfg['workflow']+'-'+digest(cfg)[:24]
        jobs.append(dict(id=identifier,config=cfg,config_sha256=digest(cfg),depends_on=list(deps),status='pending'))
        return identifier
    gates=[add(config(m,'cifar10','iid',None,'fully_connected','hybrid_pairwise_head_he',0,'gpu_gate',lr=.001)) for m in MODELS]
    smoke=[add(config(m,'cifar10','iid',None,'ring',mode,0,'smoke',lr=.001),gates) for m,mode in itertools.product(MODELS,MODES)]
    tuning={}
    for dataset,model in itertools.product(DATASETS,MODELS):
        tuning[dataset,model]=[add(config(model,dataset,split,None,'ring','none',7,'tuning',lr=lr),smoke)
            for split,lr in itertools.product(('iid','non_iid'),(.0003,.001,.003))]
    main={}
    for dataset,model,topology,(split,alpha),mode,seed in itertools.product(DATASETS,MODELS,TOPOLOGIES,SPLITS,MODES,(1,2,3)):
        cfg=config(model,dataset,split,alpha,topology,mode,seed)
        main[digest(cfg)]=add(cfg,tuning[dataset,model])
    reused=[]
    for dataset,model,(split,alpha),seed,ratio in itertools.product(DATASETS,MODELS,SPLITS,(1,2,3),RATIOS):
        if ratio==.4:
            cfg=config(model,dataset,split,alpha,'ring','adaptive_hybrid',seed)
            reused.append(dict(workflow='sensitivity',ratio=.4,source_job=main[digest(cfg)]))
        else:add(config(model,dataset,split,alpha,'ring','adaptive_hybrid',seed,'sensitivity',ratio),tuning[dataset,model])
    for dataset,model,(split,alpha),mode,seed in itertools.product(DATASETS,MODELS,SPLITS,MODES,(1,2,3)):
        add(config(model,dataset,split,alpha,'ring',mode,seed,'network'),tuning[dataset,model])
    counts={workflow:sum(j['config']['workflow']==workflow for j in jobs) for workflow in ('gpu_gate','smoke','tuning','validation','sensitivity','network')}
    body=dict(format=1,client_date='2026-11-06',protocol='independent-opaque-relay-v8',clients=50,
        evaluation_seeds=[1,2,3],tuning_seed=7,counts=counts,unique_jobs=len(jobs),
        sensitivity_references=reused,jobs=jobs,
        policy=dict(started=False,auto_start=False,GPU_gate_required=True,max_concurrent_jobs=1,
            GPU_train_workers=1,min_free_disk_GiB=12,min_available_RAM_GiB=48,
            main_training_configs_frozen_after_validation_only_LR_selection=True,
            completed_receipts_are_never_repeated=True,unverified_jobs_never_labelled_completed=True,
            historical_runs_read_only=True,retention='active_resume_checkpoints_and_verified_metrics',
            privacy='coordinator sees opaque peer traffic and secure aggregate metrics, no per-neighborhood model outputs',
            legacy_masking='explicit non-private-to-peers ablation; not a new security guarantee'))
    body['manifest_sha256']=digest(body)
    return body

def validate(manifest):
    content={k:v for k,v in manifest.items() if k!='manifest_sha256'}
    if digest(content)!=manifest['manifest_sha256']:raise ValueError('manifest hash mismatch')
    ids={j['id'] for j in manifest['jobs']}
    if len(ids)!=len(manifest['jobs']):raise ValueError('duplicate job')
    seen=set()
    for job in manifest['jobs']:
        if digest(job['config'])!=job['config_sha256'] or not set(job['depends_on'])<=seen:raise ValueError('invalid config/dependency order')
        if job['config']['clients']!=50:raise ValueError('wrong client count')
        cfg=job['config']
        if cfg['mode'] not in MODES or cfg['topology'] not in TOPOLOGIES or cfg['dataset'] not in DATASETS or cfg['training_device']!='cuda':raise ValueError('unsupported campaign settings')
        if job['config']['workflow'] in ('validation','sensitivity','network') and job['config']['seed'] not in (1,2,3):raise ValueError('wrong evaluation seed')
        seen.add(job['id'])
    return manifest['counts']
