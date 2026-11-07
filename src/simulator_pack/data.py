import hashlib,json
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import Dataset
from .design import atomic,digest

def prepare(cache,dataset,official_data):
    folder=Path(cache)/dataset;receipt=folder/'receipt.json'
    if receipt.exists():return verify(folder)
    from data_utils import get_datasets
    train,test,_=get_datasets(dataset,str(official_data));images=np.asarray(train.data);labels=np.asarray(train.targets,dtype=np.int64)
    tests=np.asarray(test.data);test_labels=np.asarray(test.targets,dtype=np.int64)
    if images.ndim==3:images=images[:,None];tests=tests[:,None]
    else:images=images.transpose(0,3,1,2);tests=tests.transpose(0,3,1,2)
    rng=np.random.default_rng(20261106);ti=[];vi=[]
    for label in range(10):
        indices=rng.permutation(np.flatnonzero(labels==label));n=round(.1*len(indices));vi.extend(indices[:n]);ti.extend(indices[n:])
    ti=np.asarray(sorted(ti));vi=np.asarray(sorted(vi));folder.mkdir(parents=True,exist_ok=True)
    sums=np.zeros(images.shape[1]);squares=sums.copy();count=0
    for lo in range(0,len(ti),256):
        x=images[ti[lo:lo+256]].astype(np.float64)/255;sums+=x.sum(axis=(0,2,3));squares+=(x*x).sum(axis=(0,2,3));count+=x.shape[0]*x.shape[2]*x.shape[3]
    mean=sums/count;std=np.sqrt(np.maximum(squares/count-mean*mean,1e-12))
    for name,im,lab in [('train',images[ti],labels[ti]),('validation',images[vi],labels[vi]),('test',tests,test_labels)]:np.savez(folder/(name+'.npz'),images=im,labels=lab)
    value=dict(dataset=dataset,input_shape=list(images.shape[1:]),train=len(ti),validation=len(vi),test=len(tests),fold_seed=20261106,
        normalization=dict(mean=mean.tolist(),std=std.tolist()),train_indices_sha256=hashlib.sha256(ti.astype('<i8').tobytes()).hexdigest(),
        validation_indices_sha256=hashlib.sha256(vi.astype('<i8').tobytes()).hexdigest(),sha256={n+'.npz':hashlib.sha256((folder/(n+'.npz')).read_bytes()).hexdigest() for n in ('train','validation','test')})
    value['receipt_sha256']=digest(value);atomic(receipt,value);return value
def verify(folder):
    folder=Path(folder);r=json.loads((folder/'receipt.json').read_text())
    if digest({k:v for k,v in r.items() if k!='receipt_sha256'})!=r['receipt_sha256']:raise RuntimeError('data receipt hash changed')
    for n,h in r['sha256'].items():
        if hashlib.sha256((folder/n).read_bytes()).hexdigest()!=h:raise RuntimeError('dataset cache changed')
    return r
class Images(Dataset):
    def __init__(self,path,metadata,augment=False):
        with np.load(path,allow_pickle=False) as ds:self.images=torch.from_numpy(ds['images'].copy()).float().div_(255);self.targets=torch.from_numpy(ds['labels'].copy()).long()
        self.mean=torch.tensor(metadata['normalization']['mean']).reshape(-1,1,1);self.std=torch.tensor(metadata['normalization']['std']).reshape(-1,1,1)
        self.augment=augment
    def __len__(self):return len(self.targets)
    def __getitem__(self,i):
        x=self.images[i]
        if self.augment:
            x=torch.nn.functional.pad(x,(4,4,4,4));a=int(torch.randint(9,()));b=int(torch.randint(9,()));x=x[:,a:a+32,b:b+32]
            if bool(torch.rand(())<.5):x=x.flip(2)
        return (x-self.mean)/self.std,int(self.targets[i])
