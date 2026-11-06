"""Persistent client owns local training/data/checkpoints and never exports them."""
import copy
import json
import math
import os
import random
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import Dataset,DataLoader
from cryptography.hazmat.primitives.asymmetric import ed25519,x25519
from client import Client
from matched_models import build_model
from secure_protocol_v4.core import Identity,Rejected,canonical,digest,decode,encode,complete
from secure_protocol_v4 import pairwise
from secure_protocol_v4.model_adapter import flatten
from secure_protocol_v6.chunked import ChunkNode
from secure_protocol_v6.node import Node
from secure_protocol_v6.rangeproof import info
from secure_protocol_v6.training_adapter import state_hash
from .common import validate_job,policy,blob_spec,he_spec,apply_aggregate,HEView,atomic_json,decode_state,round_enrollment


class PrivateImages(Dataset):
    def __init__(self,path,shape,count):
        with np.load(path,allow_pickle=False) as data:
            self.images=data['images'].copy();self.labels=data['labels'].copy()
        if self.images.dtype!=np.uint8 or self.images.shape!=(count,*shape) or self.labels.shape!=(count,) or self.labels.dtype.kind not in 'iu':
            raise Rejected('invalid local image shard')
        if np.any(self.labels<0) or np.any(self.labels>=10):
            raise Rejected('invalid local labels')
    def __len__(self):return len(self.labels)
    def __getitem__(self,i):return torch.from_numpy(self.images[i].copy()).float()/255.,int(self.labels[i])


class ClientService:
    # No get_state, local_metrics, optimizer, debug, forge, arbitrary path or upload op.
    operations={'status':set(),'train':{'round','epoch','base'},
        'enroll_round':{'messages'},
        'blob_prepare':set(),'blob_begin':{'commitments'},'blob_chunk':{'index'},
        'blob_accept_chunk':{'index','messages'},'blob_approve_blob':{'digest'},
        'blob_release_blob':{'approvals'},'he_begin':set(),'he_keygen':set(),
        'he_set_keys':{'messages'},'he_contribute':set(),
        'he_approve':{'messages','candidate'},'he_release':{'messages','candidate','approvals'},
        'finalize':{'messages','candidate','releases'},'commit':{'receipts'}}
    def __init__(self,config,*,isolation):
        self.config=config;self.root=Path(config['private_dir']).resolve();self.job=validate_job(config['job'])
        self.name=config['name'];self.isolation=isolation
        if self.name not in self.job['roster']:raise Rejected('unknown client')
        self.index=self.job['roster'].index(self.name)
        self.identity=Identity(self.name)
        secret=json.loads((self.root/'identity.json').read_text())
        self.identity.signing=ed25519.Ed25519PrivateKey.from_private_bytes(decode(secret['signing']))
        self.identity.exchange=x25519.X25519PrivateKey.from_private_bytes(decode(secret['exchange']))
        if self.identity.registration()!=self.job['enrollment'][self.name]:raise Rejected('identity differs from pinned enrollment')
        native=info()
        if native['binary_sha256']!=self.job['native_binary_sha256']:raise Rejected('native backend differs')
        torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
        torch.manual_seed(self.job['initial_seed'])
        self.model=build_model(self.job['model'],tuple(self.job['input_shape']))
        self.base=decode_state((self.root/'initial_state.b64').read_text(),self.model.state_dict())
        self.model.load_state_dict(self.base)
        if state_hash(self.base)!=self.job['initial_state_hash']:raise Rejected('initial global state mismatch')
        data=PrivateImages(self.root/'data.npz',self.job['input_shape'],self.job['partition_sizes'][self.index])
        if digest((self.root/'data.npz').read_bytes())!=config['data_sha256']:raise Rejected('private shard changed')
        self.generator=torch.Generator().manual_seed(config['training_seed'])
        self.loader=DataLoader(data,batch_size=self.job['batch_size'],shuffle=True,generator=self.generator)
        self.client=Client(self.index,self.model,self.loader,config['device'],self.job['learning_rate'])
        self.completed=0;self.active=None;self.pending=None;self.ready_receipt=None
        self.blob=None;self.he=None;self.bmean=None;self.hvalues=None;self.bvalues=None;self.commitments=None
        self.committed_receipt=None
        checkpoint=self.root/'checkpoint.pt'
        if checkpoint.exists():
            saved=torch.load(checkpoint,map_location='cpu',weights_only=False)
            if saved['job_id']!=self.job['job_id']:raise Rejected('checkpoint job mismatch')
            self.completed=saved['round'];self.base=saved['global_state'];self.client.set_state_dict(self.base)
            self.client.optimizer.load_state_dict(saved['optimizer']);self.restore_rng(saved)
            self.pending=saved.get('pending');self.ready_receipt=saved.get('ready_receipt')
            self.committed_receipt=saved.get('committed_receipt')
        elif (self.root/'inflight.json').exists():
            raise Rejected('incomplete crypto epoch requires operator recovery; refusing fresh release')
        else:
            random.seed(config['training_seed']);np.random.seed(config['training_seed']%(2**32));torch.manual_seed(config['training_seed'])
            if config['device']=='cuda':torch.cuda.manual_seed_all(config['training_seed'])
            self.save()
        if (self.root/'inflight.json').exists() and self.pending is None:
            inflight=json.loads((self.root/'inflight.json').read_text())
            if self.committed_receipt and inflight['round']==self.completed:
                (self.root/'inflight.json').unlink()
            else:raise Rejected('uncommitted cryptographic epoch; no automatic rekey/release')

    def restore_rng(self,saved):
        self.generator.set_state(saved['generator']);torch.set_rng_state(saved['torch_rng'])
        random.setstate(saved['python_rng']);np.random.set_state(saved['numpy_rng'])
        if self.config['device']=='cuda':torch.cuda.set_rng_state_all(saved['cuda_rng'])

    def save(self):
        saved=dict(job_id=self.job['job_id'],round=self.completed,global_state=self.base,
            optimizer=self.client.optimizer.state_dict(),generator=self.generator.get_state(),
            torch_rng=torch.get_rng_state(),python_rng=random.getstate(),numpy_rng=np.random.get_state(),
            cuda_rng=torch.cuda.get_rng_state_all() if self.config['device']=='cuda' else [],
            pending=self.pending,ready_receipt=self.ready_receipt,committed_receipt=self.committed_receipt)
        path=self.root/'checkpoint.pt';temp=self.root/'checkpoint.pt.tmp'
        with temp.open('wb') as stream:
            os.fchmod(stream.fileno(),0o600)
            torch.save(saved,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
        fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def rpc(self,op,args):
        if op not in self.operations or not isinstance(args,dict) or set(args)!=self.operations[op]:raise Rejected('operation/arguments rejected')
        if op=='status':
            return dict(name=self.name,job_id=self.job['job_id'],completed_round=self.completed,
                global_state_hash=state_hash(self.base),pending=bool(self.pending),pid=os.getpid(),
                isolation=self.isolation,registration=self.identity.registration())
        if op=='commit':return self.commit(args['receipts'])
        if self.pending is not None:raise Rejected('pending global commit must finish first')
        if op=='train':return self.train(**args)
        if self.active is None:raise Rejected('no trained round')
        if op=='enroll_round':
            if self.blob is not None or self.training_receipt not in args['messages']:raise Rejected('own training receipt omitted/repeated enrollment')
            self.round_roster,spec=round_enrollment(self.job,self.base,*self.active,args['messages'])
            self.blob=ChunkNode(self.name,spec,self.root/('blob-'+str(self.active[0])+'.sqlite'))
            self.blob.identity=self.round_identity;self.blob.pin(self.round_roster)
            return dict(context=spec.tag)
        if op.startswith('blob_'):
            if self.blob is None:raise Rejected('round enrollment incomplete')
            result=self.blob.rpc(op[5:],args,self.bvalues)
            if op=='blob_begin':self.commitments=copy.deepcopy(args['commitments'])
            if op=='blob_release_blob':self.bmean=pairwise.recover(pairwise.pack(self.blob.total),self.blob.spec)
            return result
        if op=='he_begin':
            if self.bmean is None or self.he is not None:raise Rejected('backbone incomplete or repeated HE epoch')
            spec=he_spec(self.job,self.base,*self.active,self.commitments,self.bmean,self.round_roster)
            self.he=Node(self.name,spec,self.root/('he-'+str(self.active[0])+'.sqlite'))
            self.he.identity=self.round_identity;self.he.pin(self.round_roster);return dict(context=spec.tag)
        if self.he is None:raise Rejected('HE not initialized')
        if op=='he_keygen':return self.he.keygen()
        if op=='he_set_keys':
            result=self.he.set_keys(args['messages'])
            self.he.key_messages=copy.deepcopy(args['messages'])
            return result
        if op=='he_contribute':return self.he.contribution(self.hvalues)
        if op=='he_approve':return self.he.approve(args['messages'],decode(args['candidate']))
        if op=='he_release':return self.he.release(args['messages'],decode(args['candidate']),args['approvals'])
        if op=='finalize':
            candidate=decode(args['candidate'])
            if self.he.recompute(args['messages'])!=candidate:raise Rejected('final HE aggregate mismatch')
            # Verify all signed, context-bound DLEQ releases before local state apply.
            view=HEView(self.he.spec,self.round_roster,self.he.key_messages,parallelism=1)
            hm=np.asarray(view.recover(args['messages'],candidate,args['releases']))
            result=apply_aggregate(self.job,self.base,hm,self.bmean)
            self.pending=dict(round=self.active[0],epoch=self.active[1],global_state=result,global_hash=state_hash(result),blob_spec=self.blob.spec.body())
            self.ready_receipt=self.identity.sign(self.blob.spec,'global_ready',dict(global_hash=state_hash(result),round=self.active[0]))
            self.save()  # durable before returning readiness; only aggregate in this response
            self.hvalues=None;self.bvalues=None
            return self.ready_receipt
        raise Rejected('unhandled operation')

    def train(self,round,epoch,base):
        if type(round)!=int or round!=self.completed+1 or round>self.job['rounds'] or not isinstance(epoch,str) or len(epoch)!=32 or any(c not in '0123456789abcdef' for c in epoch):
            raise Rejected('round/epoch not permitted')
        if base!=state_hash(self.base) or self.active is not None:raise Rejected('base mismatch or repeated local training')
        if (self.root/'inflight.json').exists():raise Rejected('prior inflight epoch requires recovery')
        self.active=(round,epoch)
        atomic_json(self.root/'inflight.json',dict(round=round,epoch=epoch,base=base))
        self.client.set_state_dict(self.base);self.client.train_local(self.job['local_epochs'])
        local=self.client.get_state_dict();delta={}
        for name,value in self.base.items():
            if value.is_floating_point():
                delta[name]=local[name]-value
                if not torch.isfinite(delta[name]).all():raise Rejected('nonfinite local training output')
            else:
                expected=int(value)+math.ceil(len(self.loader.dataset)/self.job['batch_size'])*self.job['local_epochs']
                if int(local[name])!=expected:raise Rejected('unexpected local BN counter')
        self.hvalues,_=flatten(delta,['head.weight','head.bias'])
        self.bvalues,_=flatten(delta,[n for n in delta if n not in ('head.weight','head.bias')])
        if np.abs(self.hvalues).max()>self.job['head_bound'] or np.abs(self.bvalues).max()>self.job['backbone_bound']:
            raise Rejected('local update outside policy; no clipping')
        spec=blob_spec(self.job,self.base,round,epoch)
        self.round_identity=Identity(self.name);self.round_identity.signing=self.identity.signing
        self.training_receipt=self.identity.sign(spec,'trained',dict(base=base,round=round,policy=spec.schema,exchange=self.round_identity.registration()['exchange']))
        return copy.deepcopy(self.training_receipt)

    def commit(self,receipts):
        # Idempotent recovery when a coordinator crashes halfway through commit.
        if self.pending is None:
            if self.committed_receipt and canonical(receipts)==canonical(self.committed_receipt['receipts']):
                return self.committed_receipt['response']
            raise Rejected('no pending global state')
        from secure_protocol_v4.core import RoundSpec as BlobSpec
        spec=BlobSpec(**self.pending['blob_spec'])
        items=complete(receipts,spec,'global_ready',self.job['enrollment'])
        expected=dict(global_hash=self.pending['global_hash'],round=self.pending['round'])
        if self.ready_receipt not in receipts or any(v!=expected for v in items.values()):raise Rejected('global state consensus failed')
        self.base=self.pending['global_state'];self.completed=self.pending['round'];self.client.set_state_dict(self.base)
        response=dict(name=self.name,completed_round=self.completed,global_state_hash=state_hash(self.base))
        self.committed_receipt=dict(receipts=receipts,response=response)
        self.pending=None;self.ready_receipt=None;self.save()
        (self.root/'inflight.json').unlink(missing_ok=True)
        if self.blob:self.blob.ledger.db.close()
        if self.he:self.he.ledger.db.close()
        self.active=None;self.blob=None;self.he=None;self.bmean=None;self.commitments=None;self.round_identity=None;self.training_receipt=None
        return response
