"""Client-side secure neighbor aggregation. Every payload stays inside E2E RPCs."""
import math
from pathlib import Path
import numpy as np
from secure_protocol_v4.core import RoundSpec as BlobSpec,canonical,digest,complete,encode,decode,Rejected
from secure_protocol_v4 import pairwise as p
from secure_protocol_v4.model_adapter import flatten,restore
from secure_protocol_v6.chunked import ChunkNode,CHUNK_VALUES
from secure_protocol_v6.node import Node,RoundSpec
from secure_protocol_v6.training_adapter import state_hash
from independent_clients.common import HEView
from .envelope import seal,open_envelope

def public_mask(spec,name,index,size):
    seed=int(digest(canonical(['legacy-public-mask',spec.tag,name,index]))[:16],16)
    return np.random.default_rng(seed).integers(0,p.Q,size=size,dtype=np.int64)

class AblationChunk(ChunkNode):
    """Plain/legacy-public-mask ablations, never labelled secure aggregation."""
    def __init__(self,*args,legacy=False,**kwargs):super().__init__(*args,**kwargs);self.legacy=legacy
    def rpc(self,op,args,values):
        if op=='prepare':
            if self.raw is not None or self.roster is None:raise Rejected('repeated/not enrolled')
            vector=p.quantize(values,self.spec)
            if self.legacy:
                for index,lo in enumerate(range(0,len(vector),CHUNK_VALUES)):
                    part=vector[lo:lo+CHUNK_VALUES]
                    vector[lo:lo+len(part)]=np.mod(part+public_mask(self.spec,self.identity.name,index,len(part)),p.Q)
            self.raw=p.pack(vector)
            self.own=self.identity.sign(self.spec,'blob_commit',dict(hash=digest(self.raw),bytes=len(self.raw),chunk_values=CHUNK_VALUES))
            return self.own
        result=super().rpc(op,args,values)
        if op=='accept_chunk' and self.legacy:
            index=args['index'];lo=index*CHUNK_VALUES;hi=min(self.spec.length,lo+CHUNK_VALUES)
            for name in self.spec.roster:self.total[lo:hi]=np.mod(self.total[lo:hi]-public_mask(self.spec,name,index,hi-lo),p.Q)
        return result

class Session:
    def __init__(self,name,identity,round_roster,group,state,*,run,epoch,number,model,schema,folder,scale=65536,head_bound=2.,bound=32.):
        self.name=name;self.identity=identity;self.roster={n:round_roster[n] for n in group['roster']}
        if group['mode'] not in ('none','masking','pairwise_masking','selective_he','hybrid_pairwise_head_he'):raise Rejected('unsupported group security mode')
        self.group=group;self.state=state;self.number=number;self.scale=scale;self.head_bound=head_bound;self.bound=bound
        self.split=group['mode'] in ('selective_he','hybrid_pairwise_head_he')
        names=[n for n,v in state.items() if v.is_floating_point()]
        self.head_names=['head.weight','head.bias'];self.float_names=names
        blob_names=[n for n in names if not self.split or n not in self.head_names]
        self.values,self.bschema=flatten(state,blob_names)
        self.spec=BlobSpec(run,epoch,group['roster'][0],number,model,schema,tuple(group['roster']),len(self.values),'pairwise',scale,bound)
        cls=AblationChunk if group['mode'] in ('none','masking','selective_he') else ChunkNode
        kwargs={'legacy':group['mode']=='masking'} if cls is AblationChunk else {}
        self.blob=cls(name,self.spec,Path(folder)/(group['id']+'-blob.sqlite'),**kwargs)
        self.blob.identity=identity;self.blob.pin(self.roster)
        self.he=None;self.keys=None;self.messages=None;self.candidate=None;self.approvals=None
        self.cache={};self.inbox={};self.phase_done=set();self.received={};self.result=None;self.output_hash=None

    def emit(self,phase,index,recipient):
        label=f'{phase}:{index}'
        if recipient not in self.roster or label not in self.cache:raise Rejected('no phase contribution')
        return seal(self.identity,recipient,self.roster,self.spec.tag,label,self.cache[label])

    def ingest(self,phase,index,owner,envelope):
        label=f'{phase}:{index}'
        if owner not in self.roster or label in self.phase_done:raise Rejected('wrong owner/consumed phase')
        payload=open_envelope(self.identity,owner,self.roster,self.spec.tag,label,envelope)
        box=self.inbox.setdefault(label,{})
        if owner in box and canonical(box[owner])!=canonical(payload):raise Rejected('conflicting replay')
        box[owner]=payload
        return True

    def take(self,phase,index=0):
        label=f'{phase}:{index}';box=self.inbox.get(label,{})
        if set(box)!=set(self.roster):raise Rejected('missing peer transcript')
        self.phase_done.add(label)
        return [box[n] for n in self.spec.roster]

    def act(self,phase,index=0):
        label=f'{phase}:{index}'
        if label in self.cache or ('act:'+label) in self.phase_done:raise Rejected('repeated phase')
        result=None
        if phase=='blob_commit':result=self.blob.rpc('prepare',{},self.values)
        elif phase=='blob_begin':self.blob.rpc('begin',dict(commitments=self.take('blob_commit')),self.values)
        elif phase=='blob_chunk':result=self.blob.rpc('chunk',dict(index=index),self.values)
        elif phase=='blob_accept':
            messages=self.take('blob_chunk',index);self.blob.rpc('accept_chunk',dict(index=index,messages=messages),self.values)
            self.inbox.pop(f'blob_chunk:{index}',None);self.cache.pop(f'blob_chunk:{index}',None)
        elif phase=='blob_approval':result=self.blob.rpc('approve_blob',dict(digest=digest(p.pack(self.blob.total))),self.values)
        elif phase=='blob_release':result=self.blob.rpc('release_blob',dict(approvals=self.take('blob_approval')),self.values)
        elif phase=='blob_finish':
            items=complete(self.take('blob_release'),self.spec,'blob_release',self.roster)
            if len({v['aggregate'] for v in items.values()})!=1:raise Rejected('blob release disagreement')
            self.bmean=p.recover(p.pack(self.blob.total),self.spec)
            if not self.split:self.finish(None)
        elif phase=='he_init':
            if not self.split or not hasattr(self,'bmean') or self.he is not None:raise Rejected('unexpected HE initialization')
            binding=digest(canonical(dict(blob=self.spec.tag,commit=self.blob.commit_id,backbone=digest(p.pack(self.blob.total)))))
            hs=RoundSpec(self.spec.run,self.spec.epoch,self.spec.target,self.number,self.spec.model,binding,self.spec.roster,2570,scale=self.scale,bound=self.head_bound)
            self.he=Node(self.name,hs,Path(self.blob.ledger.db.execute('PRAGMA database_list').fetchone()[2]).with_name(self.group['id']+'-he.sqlite'))
            self.he.identity=self.identity;self.he.pin(self.roster)
        elif phase=='he_key':result=self.he.keygen()
        elif phase=='he_set_keys':self.keys=self.take('he_key');self.he.set_keys(self.keys)
        elif phase=='he_contribution':
            hv,self.hschema=flatten(self.state,self.head_names);result=self.he.contribution(hv)
        elif phase=='he_approval':
            self.messages=self.take('he_contribution');self.candidate=self.he.recompute(self.messages)
            result=self.he.approve(self.messages,self.candidate)
        elif phase=='he_release':
            self.approvals=self.take('he_approval');result=self.he.release(self.messages,self.candidate,self.approvals)
        elif phase=='he_finish':
            view=HEView(self.he.spec,self.roster,self.keys,parallelism=1)
            hm=np.asarray(view.recover(self.messages,self.candidate,self.take('he_release')))
            self.finish(hm)
        else:raise Rejected('unsupported group phase')
        self.phase_done.add('act:'+label)
        if result is not None:self.cache[label]=result
        stats={}
        if phase=='he_contribution':
            stats=dict(native_ciphertext_bytes=len(decode(result['body']['payload']['data'])),range_proof_bytes=len(decode(result['body']['payload']['range_proof'])))
        return dict(done=True,**stats)

    def finish(self,hm):
        if self.result is not None:raise Rejected('repeated group result')
        restored=restore(self.bmean,self.bschema)
        if hm is not None:restored.update(restore(hm,self.hschema))
        import torch
        self.result={n:v.clone() for n,v in self.state.items()}
        for n,array in restored.items():self.result[n]=torch.as_tensor(array,dtype=self.state[n].dtype)

    def close(self):
        self.blob.ledger.db.close()
        if self.he:self.he.ledger.db.close()

def phases(session_length,split):
    yield 'blob_commit',0,True
    yield 'blob_begin',0,False
    for index in range(math.ceil(session_length/CHUNK_VALUES)):
        yield 'blob_chunk',index,True
        yield 'blob_accept',index,False
    yield 'blob_approval',0,True
    yield 'blob_release',0,True
    yield 'blob_finish',0,False
    if split:
        for name,route in [('he_init',False),('he_key',True),('he_set_keys',False),('he_contribution',True),('he_approval',True),('he_release',True),('he_finish',False)]:
            yield name,0,route
