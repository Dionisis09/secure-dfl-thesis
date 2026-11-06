"""Private training state. This module is imported only by clients/test auditors."""
import math,os,random,time
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import Dataset,DataLoader
from matched_models import build_model
from client import Client

def save(path,state):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('wb') as stream:
        os.fchmod(stream.fileno(),0o600);torch.save(state,stream);stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,path)

def load(path):return torch.load(path,map_location='cpu',weights_only=False)

class Images(Dataset):
    def __init__(self,path,job,train=False):
        with np.load(path,allow_pickle=False) as data:self.images=data['images'].copy();self.targets=data['labels'].copy()
        if self.images.dtype!=np.uint8 or len(self.images)!=len(self.targets) or tuple(self.images.shape[1:])!=tuple(job['input_shape']):raise ValueError('invalid raw dataset shard')
        self.mean=torch.tensor(job['normalization']['mean']).reshape(-1,1,1);self.std=torch.tensor(job['normalization']['std']).reshape(-1,1,1)
        self.augment=train and job['config']['dataset']=='cifar10'
    def __len__(self):return len(self.targets)
    def __getitem__(self,i):
        x=torch.from_numpy(self.images[i].copy()).float()/255
        if self.augment:
            x=torch.nn.functional.pad(x,(4,4,4,4));a=int(torch.randint(9,()));b=int(torch.randint(9,()));x=x[:,a:a+32,b:b+32]
            if bool(torch.rand(())<.5):x=x.flip(2)
        return (x-self.mean)/self.std,int(self.targets[i])

def rng_state(generator):
    return dict(loader=generator.get_state(),torch=torch.get_rng_state(),python=random.getstate(),numpy=np.random.get_state(),cuda=torch.cuda.get_rng_state_all() if torch.cuda.is_initialized() else [])

def restore_rng(saved,generator,device):
    generator.set_state(saved['loader']);torch.set_rng_state(saved['torch']);random.setstate(saved['python']);np.random.set_state(saved['numpy'])
    if device=='cuda' and saved.get('cuda'):torch.cuda.set_rng_state_all(saved['cuda'])

def train(config,request):
    root=Path(config['private_dir']);job=config['job'];cfg=job['config'];device=cfg['training_device']
    if device=='cuda' and not torch.cuda.is_available():raise RuntimeError('GPU unavailable; CPU fallback forbidden; visible='+repr(os.environ.get('CUDA_VISIBLE_DEVICES')))
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    previous=load(root/'checkpoint.pt')
    if previous['round']!=request['round']-1:raise RuntimeError('private training round mismatch')
    data=Images(root/'data.npz',job,True);generator=torch.Generator()
    loader=DataLoader(data,batch_size=cfg['batch_size'],shuffle=True,generator=generator,num_workers=0)
    model=build_model(cfg['model'],tuple(job['input_shape']));client=Client(0,model,loader,device,cfg['learning_rate'])
    client.set_state_dict(previous['state']);client.optimizer=torch.optim.AdamW(client.model.parameters(),lr=cfg['learning_rate'],weight_decay=cfg['weight_decay'])
    if previous.get('optimizer'):client.optimizer.load_state_dict(previous['optimizer'])
    if previous.get('rng'):restore_rng(previous['rng'],generator,device)
    else:
        seed=config['training_seed'];random.seed(seed);np.random.seed(seed%(2**32));torch.manual_seed(seed);generator.manual_seed(seed)
        if device=='cuda':torch.cuda.manual_seed_all(seed)
    r=request['round'];total=cfg['rounds'];warm=min(5,total)
    factor=r/warm if r<=warm else .5*(1+math.cos(math.pi*(r-warm)/max(1,total-warm)))
    for group in client.optimizer.param_groups:group['lr']=cfg['learning_rate']*factor
    if device=='cuda':torch.cuda.reset_peak_memory_stats();torch.cuda.synchronize()
    started=time.monotonic();loss=client.train_local(cfg['local_epochs'])
    if device=='cuda':torch.cuda.synchronize()
    stats=dict(device=device,training_seconds=time.monotonic()-started,peak_GPU_allocated=torch.cuda.max_memory_allocated() if device=='cuda' else 0,
        peak_GPU_reserved=torch.cuda.max_memory_reserved() if device=='cuda' else 0)
    result=dict(round=r,state=client.get_state_dict(),optimizer=client.optimizer.state_dict(),rng=rng_state(generator),train_loss=loss,base_hash=request['base'],execution=stats)
    save(root/'trained.pt',result)
    return result

def evaluate(state,path,job):
    torch.set_num_threads(1)
    dataset=Images(path,job);loader=DataLoader(dataset,batch_size=128,shuffle=False,num_workers=0)
    model=build_model(job['config']['model'],tuple(job['input_shape']));client=Client(0,model,loader,'cpu',.01);client.set_state_dict(state)
    loss,accuracy=client.evaluate(loader)
    return [accuracy/100.,loss]
