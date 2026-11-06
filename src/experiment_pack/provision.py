"""Trusted provisioning, separate from the opaque-relay coordinator."""
import copy,json,os,secrets,shutil,socket
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import Dataset
from cryptography.hazmat.primitives import serialization
from secure_protocol_v4.core import Identity,canonical,digest,encode
from secure_protocol_v4.transport import certificates
from secure_protocol_v6.rangeproof import info
from secure_protocol_v6.training_adapter import state_hash
from matched_models import build_model
from data_utils import create_client_loaders
from independent_clients.common import atomic_json
from .groups import groups
from .runtime import source_hash
from .training import save

class Labels(Dataset):
    def __init__(self,labels):self.targets=labels
    def __len__(self):return len(self.targets)
    def __getitem__(self,index):return index,int(self.targets[index])

def refresh_transport(root,roster):
    root=Path(root).resolve();folder=root/'trusted-enrollment'
    certificates(folder,list(roster)+['coordinator'],validity_days=14)
    for name in [*roster,'coordinator']:
        target=root/name
        for source,dest in [('ca.pem','ca.pem'),(name+'.pem','tls.pem'),(name+'.key','tls.key')]:
            temporary=target/(dest+'.new');shutil.copyfile(folder/source,temporary);os.chmod(temporary,0o600);os.replace(temporary,target/dest)

def provision(root,config,data_path):
    root=Path(root).resolve();data_path=Path(data_path).resolve()
    if root.exists():raise RuntimeError('provisioning never overwrites an existing run')
    if config['clients']!=50 and not config.get('test_fixture'):raise ValueError('campaign requires 50 clients')
    if config['learning_rate'] is None:raise ValueError('resolve validation-only tuning before provisioning')
    from .manifest import MODES,TOPOLOGIES,DATASETS
    if config['mode'] not in MODES or config['topology'] not in TOPOLOGIES or config['dataset'] not in DATASETS:raise ValueError('unsupported experiment policy')
    os.umask(0o077);root.mkdir(parents=True,mode=0o700)
    metadata=json.loads((data_path/'receipt.json').read_text())
    if set(metadata['sha256'])!={'train.npz','validation.npz','test.npz'}:raise ValueError('incomplete dataset cache receipt')
    for filename,wanted in metadata['sha256'].items():
        if digest((data_path/filename).read_bytes())!=wanted:raise ValueError('dataset source checksum changed')
    with np.load(data_path/'train.npz',allow_pickle=False) as data:images=data['images'];labels=data['labels']
    indices=np.arange(len(labels))
    if config['sample_budget']:
        indices=np.random.default_rng(config['seed']).permutation(len(labels))[:config['sample_budget']]
    im=images[indices];lab=labels[indices]
    loaders=create_client_loaders(Labels(lab),config['clients'],config['batch_size'],config['split'],config['seed'],config['dirichlet_alpha'] or .5,config['dirichlet_min_samples'])
    partitions=[np.asarray(loader.dataset.indices,dtype=np.int64) for loader in loaders]
    if min(map(len,partitions))<2 or sorted(np.concatenate(partitions).tolist())!=list(range(len(lab))):raise ValueError('invalid partition coverage')
    definitions,adjacency,selected=groups(config);roster=[f'p{i:03}' for i in range(config['clients'])]
    tls=root/'trusted-enrollment';tls.mkdir();certificates(tls,roster+['coordinator'],validity_days=14)
    enrollment={}
    for name,part in zip(roster,partitions):
        folder=root/name;folder.mkdir(mode=0o700);identity=Identity(name);enrollment[name]=identity.registration()
        def raw(key):return encode(key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()))
        atomic_json(folder/'identity.json',dict(signing=raw(identity.signing),exchange=raw(identity.exchange)))
        np.savez(folder/'data.npz',images=im[part],labels=lab[part])
    job=dict(version=8,config=config,groups=definitions,adjacency=adjacency,HE_targets=selected,roster=roster,enrollment=enrollment,
        partition_sizes=[len(p) for p in partitions],partition_indices_sha256=[digest(indices[p].astype('<i8').tobytes()) for p in partitions],
        class_counts=[np.bincount(lab[p],minlength=10).tolist() for p in partitions],input_shape=metadata['input_shape'],normalization=metadata['normalization'],
        data_source=metadata,source_hash=source_hash(),native_binary_sha256=info()['binary_sha256'],deployment_nonce=secrets.token_hex(16))
    torch.set_num_threads(1);torch.manual_seed(config['seed']);model=build_model(config['model'],tuple(job['input_shape']))
    initial={n:v.clone() for n,v in model.state_dict().items()};job['initial_state_hash']=state_hash(initial);job['job_id']=digest(canonical(job))
    public=root/'public-evaluation';public.mkdir();eval_paths={}
    for kind in ['validation','test']:
        source=data_path/(kind+'.npz');target=public/(kind+'.npz')
        if config['evaluation_budget']:
            with np.load(source,allow_pickle=False) as data:
                ix=np.random.default_rng(20261106).permutation(len(data['labels']))[:config['evaluation_budget']]
                np.savez(target,images=data['images'][ix],labels=data['labels'][ix])
        else:
            try:os.link(source,target)
            except OSError:shutil.copyfile(source,target)
        eval_paths[kind]=str(target)
    coord=root/'coordinator';coord.mkdir(mode=0o700);endpoints={};ports=[]
    try:
        for name in roster:
            sock=socket.socket();sock.bind(('127.0.0.1',0));ports.append(sock);endpoints[name]=dict(host='localhost',port=sock.getsockname()[1])
        for name,folder in [(n,root/n) for n in roster]+[('coordinator',coord)]:
            for source,target in [('ca.pem','ca.pem'),(name+'.pem','tls.pem'),(name+'.key','tls.key')]:shutil.copyfile(tls/source,folder/target)
            if name!='coordinator':
                # Same loader/augmentation stream for both architectures and
                # every mode/topology at a given dataset/seed/client.
                seed=int(digest(canonical([config['dataset'],config['seed'],name]))[:8],16)%(2**31)
                cfg=dict(name=name,private_dir=str(folder),job=job,port=endpoints[name]['port'],bind='127.0.0.1',training_seed=seed,
                    validation_path=eval_paths['validation'],test_path=eval_paths['test'])
                save(folder/'checkpoint.pt',dict(round=0,state=initial,optimizer=None,rng=None))
            else:cfg=dict(private_dir=str(folder),job=job,endpoints=endpoints,parallelism=2)
            atomic_json(folder/'config.json',cfg)
    finally:
        for sock in ports:sock.close()
    atomic_json(root/'public_job.json',job)
    (root/'.experiment-pack-owned').write_text(job['job_id'])
    return root
