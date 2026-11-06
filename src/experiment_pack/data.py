"""Trusted offline dataset preparation and deterministic non-overlapping folds."""
import json
from pathlib import Path
import numpy as np
from .manifest import digest

def stratified(labels,fraction=.1,seed=20261106):
    rng=np.random.default_rng(seed);train=[];validation=[]
    for label in np.unique(labels):
        ix=rng.permutation(np.flatnonzero(labels==label));count=round(len(ix)*fraction)
        validation.extend(ix[:count]);train.extend(ix[count:])
    return np.asarray(sorted(train),dtype=np.int64),np.asarray(sorted(validation),dtype=np.int64)

def prepare(cache,dataset,download=True):
    cache=Path(cache).resolve();cache.mkdir(parents=True,exist_ok=True)
    ready=cache/dataset/'receipt.json'
    if ready.exists():
        receipt=json.loads(ready.read_text())
        import hashlib
        for name,wanted in receipt['sha256'].items():
            if hashlib.sha256((ready.parent/name).read_bytes()).hexdigest()!=wanted:raise ValueError('dataset cache changed')
        return ready.parent
    from data_utils import get_datasets
    train,test,spec=get_datasets(dataset,str(cache/'official'))
    images=np.asarray(train.data);targets=np.asarray(train.targets,dtype=np.int64)
    tests=np.asarray(test.data);test_labels=np.asarray(test.targets,dtype=np.int64)
    if images.ndim==3:images=images[:,None];tests=tests[:,None]
    else:images=images.transpose(0,3,1,2);tests=tests.transpose(0,3,1,2)
    ti,vi=stratified(targets)
    output=cache/dataset;output.mkdir(exist_ok=True)
    for name,im,lab in [('train',images[ti],targets[ti]),('validation',images[vi],targets[vi]),('test',tests,test_labels)]:
        np.savez(output/(name+'.npz'),images=im,labels=lab)
    # Channel moments from the training fold only, with bounded temporary memory.
    sums=np.zeros(images.shape[1]);squares=sums.copy();pixels=0
    for lo in range(0,len(ti),256):
        block=images[ti[lo:lo+256]].astype(np.float64)/255.
        sums+=block.sum(axis=(0,2,3));squares+=(block*block).sum(axis=(0,2,3));pixels+=block.shape[0]*block.shape[2]*block.shape[3]
    mean=sums/pixels;std=np.sqrt(np.maximum(squares/pixels-mean*mean,1e-12))
    import hashlib
    receipt=dict(dataset=dataset,fold_seed=20261106,train=len(ti),validation=len(vi),test=len(tests),
        training_indices_sha256=hashlib.sha256(ti.astype('<i8').tobytes()).hexdigest(),validation_indices_sha256=hashlib.sha256(vi.astype('<i8').tobytes()).hexdigest(),
        normalization=dict(mean=mean.tolist(),std=std.tolist()),input_shape=list(images.shape[1:]),
        sha256={name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in ['train.npz','validation.npz','test.npz']})
    ready.write_text(json.dumps(receipt,indent=2)+'\n')
    return output
