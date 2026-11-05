"""Checkpointed MLP/CNN FL simulation using mandatory v6 HE range proofs.

The existing simulator owns all local models/data. Crypto RPCs receive protected
updates; independent-client data/process isolation is not claimed.
"""
import copy,csv,hashlib,json,os,random,time,platform,importlib.metadata
from contextlib import contextmanager
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import Dataset,Subset,DataLoader
from client import Client
from data_utils import set_seed,create_client_loaders,get_datasets,DATASET_SPECS
from matched_models import build_model
from secure_protocol_v4.core import canonical,digest,Rejected
from secure_protocol_v6.training_adapter import secure_average,state_hash
from secure_protocol_v6.rangeproof import info

class ArchiveImages(Dataset):
    def __init__(self,images,targets):
        if images.dtype!=np.uint8 or images.ndim!=4 or images.shape[1:]!=(32,32,3) or len(images)!=len(targets):raise ValueError('expected real CIFAR10 archive arrays')
        if np.min(targets)<0 or np.max(targets)>9:raise ValueError('invalid CIFAR10 labels')
        self.images=images;self.targets=targets
    def __len__(self):return len(self.targets)
    def __getitem__(self,index):return torch.from_numpy(self.images[index].copy()).permute(2,0,1).float().div_(255),int(self.targets[index])

def atomic_json(path,value):
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');os.replace(temp,path)
def csv_save(path,rows):
    if not rows:return
    temp=path.with_suffix('.csv.tmp')
    with temp.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    os.replace(temp,path)
@contextmanager
def run_lock(path):
    with path.open('a+b') as stream:
        if os.name=='nt':
            import msvcrt
            stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            if os.name=='nt':stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)

def source_snapshot():
    root=Path(__file__).resolve().parents[1]
    files=sorted((root/'src').rglob('*.py'))+[root/'scripts/run_secure_training.py',root/'native/dfl_range/Cargo.toml',root/'native/dfl_range/Cargo.lock',root/'native/dfl_range/src/lib.rs']
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest() for p in files}
def synchronize(device):
    if device.startswith('cuda'):torch.cuda.synchronize()

def execute(args):
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    if os.name!='nt':os.chmod(out,0o700)
    with run_lock(out/'run.lock'):return _execute(args,out)
def _execute(args,out):
    if args.clients<3 or args.clients>100 or args.rounds<1 or args.local_epochs<1:raise ValueError('invalid training policy')
    if args.train_samples<0 or args.test_samples<0 or args.batch_size<1 or not 0<args.learning_rate<1 or args.parallelism<1 or args.max_new_rounds<0:raise ValueError('invalid sampling/execution policy')
    from secure_protocol_v6.node import RoundSpec
    roster=tuple(f'p{i:03}' for i in range(args.clients))
    RoundSpec('preflight','preflight',roster[0],1,args.model,'preflight',roster,2570,bound=args.head_bound)
    native=info()  # Fail before local training if the proved backend is unavailable.
    torch.set_num_threads(2);set_seed(args.seed);torch.use_deterministic_algorithms(True)
    device='cuda' if torch.cuda.is_available() and args.device!='cpu' else 'cpu'
    if args.device=='cuda' and device!='cuda':raise RuntimeError('CUDA requested but unavailable')
    if args.data_archive:
        if args.dataset!='cifar10':raise ValueError('benchmark archive is CIFAR10 only')
        archive=Path(args.data_archive);data=np.load(archive,allow_pickle=False)
        train=ArchiveImages(data['train_images'],data['train_labels']);test=ArchiveImages(data['test_images'],data['test_labels'])
        dataset_id=dict(kind='real_CIFAR10_benchmark_archive',sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),source_train=len(train),source_test=len(test))
        spec=DATASET_SPECS['cifar10']
    else:
        train,test,spec=get_datasets(args.dataset,args.data_dir)
        h=hashlib.sha256()
        for dataset in (train,test):h.update(np.asarray(dataset.data).tobytes());h.update(np.asarray(dataset.targets,dtype='<i8').tobytes())
        dataset_id=dict(kind='torchvision_official',sha256=h.hexdigest(),source_train=len(train),source_test=len(test))
    rng=np.random.default_rng(args.seed);indices=rng.permutation(len(train))[:args.train_samples or len(train)].tolist()
    test_indices=np.random.default_rng(args.seed+999).permutation(len(test))[:args.test_samples or len(test)].tolist()
    if len(indices)<2*args.clients:raise ValueError('need at least two training samples per client')
    loaders=create_client_loaders(Subset(train,indices),args.clients,args.batch_size,args.split,args.seed,args.alpha,1)
    test_loader=DataLoader(Subset(test,test_indices),batch_size=128,shuffle=False)
    initial=build_model(args.model,spec.input_shape);parameter_count=sum(p.numel() for p in initial.parameters())
    clients=[Client(i,copy.deepcopy(initial),loaders[i],device,args.learning_rate) for i in range(args.clients)]
    source=source_snapshot();partition_hashes=[digest(canonical([indices[int(j)] for j in loader.dataset.indices])) for loader in loaders]
    runtime=dict(python=platform.python_version(),platform=platform.platform(),torch=str(torch.__version__),cuda=torch.version.cuda,cudnn=torch.backends.cudnn.version(),
        device_name=torch.cuda.get_device_name(0) if device=='cuda' else 'CPU',cpu_threads=torch.get_num_threads(),crypto_parallelism=args.parallelism,
        packages={name:importlib.metadata.version(name) for name in ['torch','torchvision','numpy','Pillow','rbcl','barriers','cryptography','cffi','pycparser']})
    config=dict(model=args.model,dataset=args.dataset,clients=args.clients,rounds=args.rounds,local_epochs=args.local_epochs,batch_size=args.batch_size,runtime=runtime,
        learning_rate=args.learning_rate,split=args.split,alpha=args.alpha,seed=args.seed,device=device,parameter_count=parameter_count,
        head_bound=args.head_bound,backbone_bound=32.,scale=65536,topology='full',aggregation_weights='uniform',
        dataset_source=dataset_id,train_samples=len(indices),test_samples=len(test_indices),partition_sizes=[len(l.dataset) for l in loaders],partition_sha256=partition_hashes,
        evaluation_indices_sha256=digest(canonical(test_indices)),source_sha256=source,native_binary_sha256=native['binary_sha256'],
        privacy_scope='Trusted-host FL simulator owns plaintext local states; no independent-client isolation claim')
    config_id=digest(canonical(config));checkpoint=out/'checkpoint.pt';records=[];details=[];completed=0
    if checkpoint.exists():
        if not args.resume:raise RuntimeError('checkpoint exists; use --resume, never silently overwrite')
        saved=torch.load(checkpoint,map_location='cpu',weights_only=False)
        if saved['config_id']!=config_id:raise RuntimeError('resume config/source/data mismatch')
        for client,opt,loader,loader_state in zip(clients,saved['optimizers'],loaders,saved['loader_generators']):
            client.set_state_dict(saved['aggregate_state']);client.optimizer.load_state_dict(opt);loader.generator.set_state(loader_state)
        torch.set_rng_state(saved['torch_rng']);random.setstate(saved['python_rng']);np.random.set_state(saved['numpy_rng'])
        if device=='cuda':torch.cuda.set_rng_state_all(saved['cuda_rng'])
        completed=saved['completed_round'];records=saved['records'];details=saved['details']
        if state_hash(clients[0].get_state_dict())!=saved['aggregate_state_hash']:raise RuntimeError('checkpoint state hash mismatch')
    elif args.resume:raise RuntimeError('no checkpoint to resume')
    else:
        atomic_json(out/'config.json',dict(config_id=config_id,**config))
    def save(round_number):
        state=clients[0].get_state_dict();snapshot=dict(config_id=config_id,completed_round=round_number,aggregate_state=state,aggregate_state_hash=state_hash(state),
            optimizers=[c.optimizer.state_dict() for c in clients],loader_generators=[l.generator.get_state() for l in loaders],torch_rng=torch.get_rng_state(),
            cuda_rng=torch.cuda.get_rng_state_all() if device=='cuda' else [],python_rng=random.getstate(),numpy_rng=np.random.get_state(),records=records,details=details)
        temp=checkpoint.with_suffix('.pt.tmp');torch.save(snapshot,temp);os.replace(temp,checkpoint)
        if os.name!='nt':os.chmod(checkpoint,0o600)
        csv_save(out/'metrics.csv',records);atomic_json(out/'round_evidence.json',details)
    if not checkpoint.exists():save(0)
    completed_at_start=completed
    atomic_json(out/'progress.json',dict(status='running',completed_round=completed,planned_rounds=args.rounds,config_id=config_id))
    try:
        for number in range(completed+1,args.rounds+1):
            if args.preflight_only:break
            if args.max_new_rounds and number-completed_at_start>args.max_new_rounds:break
            print(json.dumps(dict(model=args.model,round=number,stage='local_training',clients=args.clients)),flush=True)
            base=clients[0].get_state_dict();synchronize(device);started=time.monotonic()
            losses=[client.train_local(args.local_epochs) for client in clients]
            synchronize(device);training_seconds=time.monotonic()-started;states=[client.get_state_dict() for client in clients]
            print(json.dumps(dict(model=args.model,round=number,stage='range_proved_hybrid_aggregation')),flush=True)
            aggregate,detail,control=secure_average(states,base,run=config_id,round_number=number,model_id=args.model,head_bound=args.head_bound,parallelism=args.parallelism)
            for client in clients:client.set_state_dict(aggregate)
            hashes=[state_hash(client.get_state_dict()) for client in clients]
            if len(set(hashes))!=1 or hashes[0]!=detail['aggregate_state_hash']:raise Rejected('model apply disagreement')
            loss,accuracy=clients[0].evaluate(test_loader)
            reference=Client(-1,copy.deepcopy(initial),loaders[0],device,args.learning_rate);reference.set_state_dict(control)
            reference_loss,reference_accuracy=reference.evaluate(test_loader);del reference
            if accuracy!=reference_accuracy or abs(loss-reference_loss)>1e-7:raise Rejected('evaluation differs from quantized plaintext control')
            detail.update(round=number,model=args.model,source_snapshot_hash=digest(canonical(source)),training_seconds=training_seconds,all_client_state_hashes=hashes,
                test_accuracy=accuracy,test_loss=loss,control_test_accuracy=reference_accuracy,control_test_loss=reference_loss)
            details.append(detail);records.append(dict(round=number,train_loss=float(np.mean(losses)),test_loss=loss,test_accuracy=accuracy,control_test_loss=reference_loss,
                control_test_accuracy=reference_accuracy,training_seconds=training_seconds,aggregation_seconds=detail['total_aggregation_seconds'],quantized_control_max_integer_error=0,
                aggregate_state_hash=hashes[0],maximum_mean_quantization_error=detail['maximum_mean_quantization_error']))
            completed=number;save(completed)
            atomic_json(out/'progress.json',dict(status='running',completed_round=completed,planned_rounds=args.rounds,config_id=config_id))
            print(json.dumps(dict(model=args.model,round=number,stage='checkpoint_committed',test_accuracy=accuracy,quantized_control_error=0)),flush=True)
    except BaseException as error:
        atomic_json(out/'progress.json',dict(status='failed',completed_round=completed,planned_rounds=args.rounds,config_id=config_id,error_type=type(error).__name__,checkpoint_recovery='resume from last committed round'))
        raise
    status='completed' if completed==args.rounds else 'paused'
    atomic_json(out/'progress.json',dict(status=status,completed_round=completed,planned_rounds=args.rounds,config_id=config_id))
    receipt=dict(status=status,config_id=config_id,model=args.model,clients=args.clients,completed_rounds=completed,planned_rounds=args.rounds,parameter_count=parameter_count,
        resumed_from_round=completed_at_start,rounds_executed_this_invocation=completed-completed_at_start,
        preflight_only=args.preflight_only,all_quantized_controls_exact=bool(records) and all(r['quantized_control_max_integer_error']==0 for r in records),range_proofs_required=True,full_backbone_masked=True,
        checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),source_sha256=source,native_backend=native,dataset=dataset_id,
        scope='Real-data integration pilot, full uniform topology, trusted-host simulator; not a statistical model-performance campaign or isolated client deployment')
    atomic_json(out/'verification.json',receipt);print(json.dumps(receipt),flush=True);return receipt
