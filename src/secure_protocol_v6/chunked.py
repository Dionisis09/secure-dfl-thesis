"""Full-backbone finite-field masking with bounded streaming verification.

Every receiver verifies all sender chunks and complete-blob commitments before
approving. This avoids fitting an N*model transcript into a single RPC body.
"""
import hashlib,math
import numpy as np
from secure_protocol_v4.core import Identity,Ledger,Rejected,complete,decode,encode,canonical,digest
from secure_protocol_v4.node import Node as Enrollment
from secure_protocol_v4 import pairwise as p

CHUNK_VALUES=32768
class ChunkNode:
    operations={'prepare':set(),'begin':{'commitments'},'chunk':{'index'},'accept_chunk':{'index','messages'},'approve_blob':{'digest'},'release_blob':{'approvals'}}
    def __init__(self,name,spec,path):
        self.spec=spec;self.identity=Identity(name);self.ledger=Ledger(path);self.roster=None
        self.raw=None;self.own=None;self.commits=None;self.cursor=0;self.hashes=None;self.failed=False;self.total=np.zeros(spec.length,dtype=np.int64)
    def registration(self):return self.identity.registration()
    def pin(self,roster):Enrollment.pin(self,roster)
    def rpc(self,op,args,values):
        if self.failed:raise Rejected('blob transaction aborted')
        if op=='prepare':
            if self.raw is not None or self.roster is None:raise Rejected('not enrolled/repeated blob')
            self.raw=p.protect(self.identity,values,self.spec,self.roster)
            self.own=self.identity.sign(self.spec,'blob_commit',dict(hash=digest(self.raw),bytes=len(self.raw),chunk_values=CHUNK_VALUES))
            return self.own
        if op=='begin':
            if self.commits is not None or self.own is None or self.own not in args['commitments']:raise Rejected('own commitment missing/repeated transcript')
            items=complete(args['commitments'],self.spec,'blob_commit',self.roster)
            for payload in items.values():
                if set(payload)!={'hash','bytes','chunk_values'} or payload['bytes']!=8*self.spec.length or payload['chunk_values']!=CHUNK_VALUES or not isinstance(payload['hash'],str) or len(payload['hash'])!=64:raise Rejected('invalid blob commitment')
            self.commits=items;self.commit_id=digest(canonical(sorted(args['commitments'],key=lambda m:m['body']['sender'])))
            self.hashes={n:hashlib.sha256() for n in self.spec.roster};return True
        if op in ('chunk','accept_chunk'):
            index=args['index'];count=math.ceil(self.spec.length/CHUNK_VALUES)
            if type(index) is not int or not 0<=index<count or self.raw is None:raise Rejected('invalid chunk index')
            lo=index*CHUNK_VALUES;hi=min(self.spec.length,lo+CHUNK_VALUES)
            if op=='chunk':return self.identity.sign(self.spec,'blob_chunk',dict(index=index,data=encode(self.raw[8*lo:8*hi])))
            if self.commits is None or index!=self.cursor:raise Rejected('missing/out-of-order chunk')
            items=complete(args['messages'],self.spec,'blob_chunk',self.roster);raws={};total=np.zeros(hi-lo,dtype=np.int64)
            for name,payload in items.items():
                if set(payload)!={'index','data'} or type(payload['index']) is not int or payload['index']!=index:raise Rejected('wrong chunk binding')
                data=decode(payload['data']);v=np.frombuffer(data,dtype='<i8')
                if len(data)!=8*(hi-lo) or np.any(v<0) or np.any(v>=p.Q):raise Rejected('invalid modular chunk')
                if name==self.identity.name and data!=self.raw[8*lo:8*hi]:raise Rejected('own chunk changed')
                raws[name]=data;total=np.mod(total+v,p.Q)
            for name,data in raws.items():self.hashes[name].update(data)
            self.total[lo:hi]=total;self.cursor+=1
            if self.cursor==count and any(self.hashes[n].hexdigest()!=self.commits[n]['hash'] for n in self.spec.roster):
                self.failed=True;raise Rejected('blob commitment mismatch; abort')
            return True
        if self.cursor!=math.ceil(self.spec.length/CHUNK_VALUES) or self.commits is None:raise Rejected('blob verification incomplete')
        tag=digest(canonical(dict(context=self.spec.tag,commits=self.commit_id,aggregate=digest(p.pack(self.total)))))
        if op=='approve_blob':
            if args['digest']!=digest(p.pack(self.total)):raise Rejected('wrong blob aggregate')
            self.ledger.approve(self.spec.slot,tag);return self.identity.sign(self.spec,'blob_approval',dict(aggregate=tag))
        if op=='release_blob':
            items=complete(args['approvals'],self.spec,'blob_approval',self.roster)
            if any(value!=dict(aggregate=tag) for value in items.values()):raise Rejected('wrong blob approvals')
            self.ledger.consume(self.spec.slot,tag);return self.identity.sign(self.spec,'blob_release',dict(aggregate=tag))
        raise Rejected('unsupported blob operation')

def aggregate_group(group):
    """Run a complete streamed all-member masked backbone transaction."""
    commitments=group.parallel('prepare');group.parallel('begin',commitments=commitments)
    total=np.zeros(group.spec.length,dtype=np.int64)
    for index,lo in enumerate(range(0,group.spec.length,CHUNK_VALUES)):
        messages=group.parallel('chunk',index=index);items=complete(messages,group.spec,'blob_chunk',group.roster)
        hi=min(group.spec.length,lo+CHUNK_VALUES);part=np.zeros(hi-lo,dtype=np.int64)
        for payload in items.values():
            if payload['index']!=index:raise Rejected('wrong streamed index')
            v=np.frombuffer(decode(payload['data']),dtype='<i8')
            if v.shape!=(hi-lo,) or np.any(v<0) or np.any(v>=p.Q):raise Rejected('invalid streamed field')
            part=np.mod(part+v,p.Q)
        total[lo:hi]=part;group.parallel('accept_chunk',index=index,messages=messages)
    candidate=p.pack(total);approvals=group.parallel('approve_blob',digest=digest(candidate))
    releases=group.parallel('release_blob',approvals=approvals)
    items=complete(releases,group.spec,'blob_release',group.roster)
    if len({payload['aggregate'] for payload in items.values()})!=1:raise Rejected('blob release disagreement')
    return p.recover(candidate,group.spec),commitments
