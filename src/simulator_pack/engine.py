"""One-process legacy-style training, real CKKS, resumable round checkpoints."""
import copy,hashlib,json,math,os,random,time
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import DataLoader
from client import Client
from data_utils import create_client_loaders
from matched_models import build_model
from topology import build_topology
from .design import atomic,digest,source_snapshot
from .data import Images,verify
from .protection import context,mix

def cpu_tree(value):
    if torch.is_tensor(value):return value.detach().cpu().clone()
    if isinstance(value,dict):return {k:cpu_tree(v) for k,v in value.items()}
    if isinstance(value,list):return [cpu_tree(v) for v in value]
    if isinstance(value,tuple):return tuple(cpu_tree(v) for v in value)
    return value
def save(path,value):
    path=Path(path);tmp=path.with_suffix('.tmp')
    with tmp.open('wb') as f:torch.save(value,f);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def rng(generator,device):
    return dict(loader=generator.get_state(),torch=torch.get_rng_state(),python=random.getstate(),numpy=np.random.get_state(),cuda=torch.cuda.get_rng_state_all() if device=='cuda' else [])
def restore(value,generator,device):
    generator.set_state(value['loader']);torch.set_rng_state(value['torch']);random.setstate(value['python']);np.random.set_state(value['numpy'])
    if device=='cuda':torch.cuda.set_rng_state_all(value['cuda'])
def state_hash(states):
    h=hashlib.sha256()
    for state in states:
        for k,v in state.items():h.update(k.encode());h.update(str(v.dtype).encode());h.update(v.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()
def runtime(device):
    import platform,importlib.metadata
    return dict(platform=platform.platform(),python=platform.python_version(),device=device,
        GPU=torch.cuda.get_device_name(0) if device=='cuda' else None,cuda=torch.version.cuda if device=='cuda' else None,
        GPU_memory_bytes=torch.cuda.get_device_properties(0).total_memory if device=='cuda' else 0,
        packages={n:importlib.metadata.version(n) for n in ['torch','torchvision','numpy','networkx','tenseal']},FP32=True,torch_threads=1,deterministic=True)
def completed(folder,cfg=None,expected_source=None,expected_runtime=None,expected_data=None):
    folder=Path(folder)
    try:
        r=json.loads((folder/'complete.json').read_text());checks=json.loads((folder/'checksums.json').read_text())
        if r['status']!='completed' or r['completed_rounds']!=r['config']['rounds'] or (cfg is not None and digest(cfg)!=r['config_sha256']):return False
        if expected_source is not None and r['source_hash']!=expected_source:return False
        if expected_runtime is not None and r['runtime_sha256']!=expected_runtime:return False
        if expected_data is not None and r['data_receipt_sha256']!=expected_data:return False
        if not {'complete.json','metrics.json','identity.json'}<=set(checks) or any(Path(n).name!=n for n in checks):return False
        return all(hashlib.sha256((folder/n).read_bytes()).hexdigest()==h for n,h in checks.items())
    except (OSError,ValueError,KeyError):return False

def execute(folder,cfg,cache,*,device='cuda',deadline=None,max_new_rounds=None,keep_checkpoint=False):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True);source=source_snapshot()['hash']
    if cfg['clients'] not in (20,50,100) and not cfg.get('test_fixture'):raise ValueError('supported scientific client counts are20/50/100')
    if completed(folder,cfg):
        receipt=json.loads((folder/'complete.json').read_text())
        if receipt['source_hash']!=source:raise RuntimeError('completed result has a different source snapshot')
        return dict(receipt,no_op=True)
    if (folder/'complete.json').exists():raise RuntimeError('completed archive invalid; operator review required, no retraining')
    if device=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA unavailable; no CPU fallback')
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8');torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True
    profile=runtime(device);metadata=verify(Path(cache)/cfg['dataset'])
    identity=dict(config=cfg,config_sha256=digest(cfg),source_hash=source,data_receipt_sha256=metadata['receipt_sha256'],runtime_profile=profile,runtime_sha256=digest(profile))
    if (folder/'identity.json').exists() and json.loads((folder/'identity.json').read_text())!=identity:raise RuntimeError('config/source/data/runtime drift; refusing resume')
    atomic(folder/'identity.json',identity);setup=time.perf_counter()
    train=Images(Path(cache)/cfg['dataset']/'train.npz',metadata,cfg['dataset']=='cifar10')
    validation=DataLoader(Images(Path(cache)/cfg['dataset']/'validation.npz',metadata),batch_size=128,shuffle=False)
    test=DataLoader(Images(Path(cache)/cfg['dataset']/'test.npz',metadata),batch_size=128,shuffle=False)
    loaders=create_client_loaders(train,cfg['clients'],cfg['batch_size'],cfg['split'],cfg['seed'],cfg['alpha'] or .5,cfg['dirichlet_min_samples'],cfg['shards_per_client'])
    graph=build_topology(cfg['topology'],cfg['clients'],cfg['seed'],cfg['caveman_cliques'],cfg['barabasi_m'])
    torch.manual_seed(cfg['seed']);initial=build_model(cfg['model'],tuple(metadata['input_shape']));initial_state=cpu_tree(initial.state_dict());clients=[];streams=[]
    parameters=sum(p.numel() for p in initial.parameters());head=initial.head.weight.numel()+initial.head.bias.numel()
    for i,loader in enumerate(loaders):
        model=build_model(cfg['model'],tuple(metadata['input_shape']));model.load_state_dict(initial_state)
        client=Client(i,model,loader,device,cfg['learning_rate'],defer_metrics=True)
        client.optimizer=torch.optim.AdamW(client.model.parameters(),lr=cfg['learning_rate'],weight_decay=cfg['weight_decay']);clients.append(client)
        seed=int(digest([cfg['dataset'],cfg['seed'],i])[:8],16)%(2**31);random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
        if device=='cuda':torch.cuda.manual_seed_all(seed)
        loader.generator.manual_seed(seed);streams.append(rng(loader.generator,device))
    del initial
    sizes=[len(l.dataset) for l in loaders];indices=[list(map(int,l.dataset.indices)) for l in loaders]
    if sorted(i for group in indices for i in group)!=list(range(len(train))):raise RuntimeError('partition coverage invalid')
    description=dict(parameter_count=parameters,head_values=head,partition_sizes=sizes,
        partition_hashes=[digest(g) for g in indices],class_counts=[np.bincount(train.targets[g].numpy(),minlength=10).tolist() for g in indices],
        adjacency=graph,common_initial_state_hash=state_hash([initial_state]),normalization=metadata['normalization'],input_shape=metadata['input_shape'],
        primary_metric='uniform mean client accuracy/loss on shared evaluation set',simulator_trainer_has_plaintexts_and_keys=True)
    if (folder/'model_data.json').exists() and json.loads((folder/'model_data.json').read_text())!=json.loads(json.dumps(description)):raise RuntimeError('partition/model drift')
    atomic(folder/'model_data.json',description)
    contexts={i:context(cfg['CKKS']) for i in graph} if cfg['mode'] in ('selective_he','adaptive_hybrid') else {}
    checkpoint=folder/'checkpoint.pt';records=[];best=None;best_score=-float('inf');start=0;resumes=0;total_setup=time.perf_counter()-setup
    if checkpoint.exists():
        saved=torch.load(checkpoint,map_location='cpu',weights_only=False)
        if saved['identity_sha256']!=digest(identity):raise RuntimeError('checkpoint provenance mismatch')
        for c,s,o in zip(clients,saved['states'],saved['optimizers']):c.set_state_dict(s);c.optimizer.load_state_dict(o)
        streams=saved['streams'];records=saved['records'];best=saved['best'];best_score=saved['best_score'];start=saved['round'];resumes=saved['resumes']+1;total_setup+=saved['setup_seconds']
        timing=folder/'checkpoint_timing.json'
        if timing.exists():
            timing=json.loads(timing.read_text())
            if timing['round']==start:records[-1].update(timing['record'])
    session_start=time.perf_counter()
    def sync():
        if device=='cuda':torch.cuda.synchronize()
    def evaluate(loader,override=None):
        losses=[];accuracies=[]
        for i,c in enumerate(clients):
            if override is not None:c.set_state_dict(override[i])
            loss,accuracy=c.evaluate(loader);losses.append(loss);accuracies.append(accuracy)
        return dict(accuracy=sum(accuracies)/len(clients),loss=sum(losses)/len(clients))
    last_states=None
    for number in range(start+1,cfg['rounds']+1):
        if (deadline is not None and time.time()>=deadline) or (folder/'pause.request').exists() or (max_new_rounds is not None and number-start>max_new_rounds):break
        t0=time.perf_counter();sync();before={i:{n:c.model.state_dict()[n].detach().cpu().clone() for n in ['head.weight','head.bias']} for i,c in enumerate(clients)} if cfg['mode']=='adaptive_hybrid' else {}
        t=time.perf_counter();losses=[]
        factor=number/cfg['warmup_rounds'] if number<=cfg['warmup_rounds'] else .5*(1+math.cos(math.pi*(number-cfg['warmup_rounds'])/max(1,cfg['schedule_rounds']-cfg['warmup_rounds'])))
        for i,c in enumerate(clients):
            restore(streams[i],c.train_loader.generator,device)
            for group in c.optimizer.param_groups:group['lr']=cfg['learning_rate']*factor
            losses.append(c.train_local(cfg['local_epochs']));streams[i]=rng(c.train_loader.generator,device)
        sync();training_seconds=time.perf_counter()-t
        t=time.perf_counter();previous={i:c.get_state_dict() for i,c in enumerate(clients)};snapshot_seconds=time.perf_counter()-t
        mixed,statistics=mix(previous,before,graph,cfg,contexts,number)
        t=time.perf_counter()
        for i,c in enumerate(clients):c.set_state_dict(mixed[i])
        sync();load_seconds=time.perf_counter()-t;last_states=[mixed[i] for i in range(len(clients))]
        t=time.perf_counter();score=evaluate(validation) if number%cfg['validation_every']==0 or number==cfg['rounds'] else None;sync();evaluation_seconds=time.perf_counter()-t
        if score is not None and score['accuracy']>best_score:best_score=score['accuracy'];best=copy.deepcopy(last_states)
        record=dict(round=number,train_loss=sum(losses)/len(losses),validation=score,training_seconds=training_seconds,snapshot_seconds=snapshot_seconds,load_seconds=load_seconds,
            validation_seconds=evaluation_seconds,checkpoint_seconds=None,round_seconds=None,timing_complete=False,**statistics);records.append(record)
        t=time.perf_counter()
        save(checkpoint,dict(identity_sha256=digest(identity),round=number,states=last_states,optimizers=[cpu_tree(c.optimizer.state_dict()) for c in clients],streams=streams,records=records,
            best=best,best_score=best_score,resumes=resumes,setup_seconds=total_setup))
        record.update(checkpoint_seconds=time.perf_counter()-t,round_seconds=time.perf_counter()-t0,timing_complete=True)
        atomic(folder/'checkpoint_timing.json',dict(round=number,record=record));atomic(folder/'progress.json',dict(completed=number,planned=cfg['rounds'],last_round=record))
        print(json.dumps(dict(round=number,planned=cfg['rounds'],round_seconds=record['round_seconds'],validation=score)),flush=True)
        del previous,mixed
    done=records[-1]['round'] if records else start
    if done!=cfg['rounds']:return dict(status='paused',completed_rounds=done)
    if last_states is None:last_states=[c.get_state_dict() for c in clients]
    t=time.perf_counter();final_test=evaluate(test);sync();final_test_seconds=time.perf_counter()-t
    t=time.perf_counter();best_test=evaluate(test,best);sync();best_test_seconds=time.perf_counter()-t
    for c,s in zip(clients,last_states):c.set_state_dict(s)
    atomic(folder/'metrics.json',records)
    receipt=dict(status='completed',config=cfg,config_sha256=digest(cfg),source_hash=source,data_receipt_sha256=metadata['receipt_sha256'],runtime_profile=profile,runtime_sha256=digest(profile),
        completed_rounds=done,setup_seconds=total_setup,session_wall_seconds=time.perf_counter()-session_start+total_setup,resume_count=resumes,
        final_test=final_test,best_validation_test=best_test,best_validation_accuracy=best_score,test_final_seconds=final_test_seconds,test_best_seconds=best_test_seconds,
        final_state_hash=state_hash(last_states),checkpoint_retained=keep_checkpoint,threat_model=cfg['threat_model'],communication='calculated state/ciphertext payload; not measured network',test_used_for_tuning=False,
        recorded_job_seconds=total_setup+sum(r['round_seconds'] for r in records)+final_test_seconds+best_test_seconds if all(r['timing_complete'] for r in records) else None)
    atomic(folder/'complete.json',receipt)
    names=['complete.json','metrics.json','identity.json','model_data.json'];atomic(folder/'checksums.json',{n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in names})
    if not completed(folder,cfg):raise RuntimeError('completion verification failed; checkpoints retained')
    if not keep_checkpoint:checkpoint.unlink()
    return receipt
