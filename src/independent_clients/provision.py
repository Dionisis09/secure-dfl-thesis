"""Trusted offline fixture provisioning. This code is NOT part of the trainer.

For real separate hosts, distribute each private directory to its own operator
and issue endpoint-valid TLS certificates. The coordinator gets only its own
TLS key, public enrollment/job policy and client endpoints.
"""
import json
import os
import secrets
import shutil
import socket
from pathlib import Path
import numpy as np
import torch
from cryptography.hazmat.primitives import serialization
from matched_models import build_model
from secure_protocol_v4.core import Identity,digest,canonical,encode
from secure_protocol_v4.transport import certificates
from secure_protocol_v6.rangeproof import info
from secure_protocol_v6.training_adapter import state_hash
from .common import code_hash,atomic_json,encode_state


def provision(root,archive,*,model,clients=20,rounds=2,train_samples=640,batch_size=16,device='cuda'):
    root=Path(root).resolve()
    if root.exists():raise RuntimeError('refusing to overwrite enrollment; use a new job directory')
    os.umask(0o077);root.mkdir(parents=True,mode=0o700)
    roster=[f'p{i:03}' for i in range(clients)]
    if not 3<=clients<=50 or train_samples<2*clients:raise ValueError('invalid client/sample scope')
    with np.load(archive,allow_pickle=False) as source:
        images=source['train_images'];labels=source['train_labels']
        if images.dtype!=np.uint8 or images.ndim!=4 or images.shape[1:]!=(32,32,3):raise ValueError('real CIFAR10 archive required')
        if train_samples>len(images):raise ValueError('insufficient images')
        indices=np.random.default_rng(1).permutation(len(images))[:train_samples]
        partitions=np.array_split(indices,clients)
        paths={};enrollment={}
        for name,part in zip(roster,partitions):
            folder=root/name;folder.mkdir(mode=0o700);paths[name]=folder
            np.savez(folder/'data.npz',images=images[part].transpose(0,3,1,2),labels=labels[part])
            identity=Identity(name);enrollment[name]=identity.registration()
            def raw(key):return encode(key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()))
            atomic_json(folder/'identity.json',dict(signing=raw(identity.signing),exchange=raw(identity.exchange)))
    coordinator=root/'coordinator';coordinator.mkdir(mode=0o700)
    tls=root/'trusted-enrollment';tls.mkdir(mode=0o700);certificates(tls,roster+['coordinator'])
    for name,folder in [*paths.items(),('coordinator',coordinator)]:
        shutil.copyfile(tls/'ca.pem',folder/'ca.pem')
        shutil.copyfile(tls/(name+'.pem'),folder/'tls.pem');shutil.copyfile(tls/(name+'.key'),folder/'tls.key')
        os.chmod(folder/'tls.key',0o600)
    torch.set_num_threads(1);torch.manual_seed(1);initial=build_model(model,(3,32,32))
    initial_wire=encode_state(initial.state_dict())
    for folder in [*paths.values(),coordinator]:
        (folder/'initial_state.b64').write_text(initial_wire)
    job=dict(version=7,model=model,input_shape=[3,32,32],roster=roster,enrollment=enrollment,
        rounds=rounds,batch_size=batch_size,local_epochs=1,learning_rate=.01,
        initial_seed=1,initial_state_hash=state_hash(initial.state_dict()),
        partition_sizes=[len(p) for p in partitions],topology='full',weights='uniform',
        scale=65536,head_bound=1.,backbone_bound=32.,source_hash=code_hash(),
        native_binary_sha256=info()['binary_sha256'],deployment_id=secrets.token_hex(16))
    job['job_id']=digest(canonical(job));endpoints={};sockets=[]
    try:
        for name,folder in paths.items():
            sock=socket.socket();sock.bind(('127.0.0.1',0));sockets.append(sock);port=sock.getsockname()[1]
            endpoints[name]=dict(host='localhost',port=port)
            private=dict(name=name,private_dir=str(folder),job=job,bind='127.0.0.1',port=port,device=device,
                training_seed=secrets.randbits(31),data_sha256=digest((folder/'data.npz').read_bytes()))
            atomic_json(folder/'config.json',private)
        atomic_json(coordinator/'config.json',dict(private_dir=str(coordinator),job=job,endpoints=endpoints,parallelism=4))
    finally:
        for sock in sockets:sock.close()
    atomic_json(root/'public_job.json',job)
    atomic_json(root/'provisioning_receipt.json',dict(job_id=job['job_id'],source_archive_sha256=digest(Path(archive).read_bytes()),
        private_paths_not_distributed_to_coordinator=True,scope='trusted offline provisioner sees fixture data and enrollment keys; not trainer'))
    return root
