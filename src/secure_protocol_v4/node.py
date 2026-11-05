"""Per-node state machine. Never returns signing/DH keys or HE private shares."""
import numpy as np
from .core import Identity,Ledger,Rejected,canonical,digest,encode,decode,complete,aggregate_tag
from . import pairwise

class Node:
    def __init__(self,name,spec,ledger_path,context=None):
        if name not in spec.roster:raise Rejected('unknown node')
        self.identity=Identity(name);self.spec=spec;self.ledger=Ledger(ledger_path);self.roster=None
        self.crypto=None;self.secret=None;self.pk=None;self.own=None
        if spec.kind=='he_bfv':
            from .openfhe_backend import MultipartyBFV
            if spec.bound*MultipartyBFV.SCALE*len(spec.roster)>=MultipartyBFV.MODULUS//4:
                raise Rejected('BFV fixed-point aggregate may wrap')
            self.crypto=MultipartyBFV(context,parties=len(spec.roster))
    def registration(self):return self.identity.registration()
    def pin(self,roster):
        if self.roster is not None or set(roster)!=set(self.spec.roster) or roster[self.identity.name]!=self.registration():
            raise Rejected('invalid/pinned identity roster')
        # Supplied only by the trusted experiment enrollment/control plane.
        self.roster=roster
    def keygen(self,previous,chain):
        index=self.spec.roster.index(self.identity.name)
        if self.secret is not None or len(chain)!=index:raise Rejected('invalid key ceremony order')
        self.check_chain(chain)
        if (index==0 and previous is not None) or (index>0 and previous!=decode(chain[-1]['body']['payload']['key'])):
            raise Rejected('wrong previous key')
        self.secret,pub=self.crypto.keygen(previous)
        return self.identity.sign(self.spec,'keygen',dict(previous=digest(previous or b''),key=encode(pub)))
    def check_chain(self,chain):
        from .core import verify
        previous=b''
        for index,msg in enumerate(chain):
            sender,p=verify(msg,self.spec,'keygen',self.roster)
            if sender!=self.spec.roster[index] or p['previous']!=digest(previous):raise Rejected('invalid key chain')
            previous=decode(p['key'])
    def set_key(self,chain):
        if len(chain)!=len(self.spec.roster) or self.pk is not None:raise Rejected('incomplete/repeated key ceremony')
        self.check_chain(chain);self.pk=decode(chain[-1]['body']['payload']['key'])
    def contribution(self,values):
        if self.own is not None:raise Rejected('duplicate contribution')
        if self.roster is None:raise Rejected('not enrolled')
        v=np.asarray(values,dtype=np.float64)
        if v.shape!=(self.spec.length,) or not np.isfinite(v).all() or np.abs(v).max()>self.spec.bound:raise Rejected('invalid input')
        if self.spec.kind=='he_bfv':
            if self.pk is None:raise Rejected('no approved public key')
            payload=self.crypto.encrypt(self.pk,v)
        else:payload=pairwise.protect(self.identity,v,self.spec,self.roster)
        self.own=self.identity.sign(self.spec,'contribution',dict(data=encode(payload)))
        return self.own
    def recompute(self,messages):
        items=complete(messages,self.spec,'contribution',self.roster)
        if self.own not in messages:raise Rejected('own committed contribution missing')
        payloads=[decode(items[k]['data']) for k in self.spec.roster]
        return self.crypto.average(payloads,len(payloads)) if self.crypto else pairwise.sum_vectors(payloads,self.spec)
    def approve(self,messages,candidate):
        actual=self.recompute(messages)
        if actual!=candidate:raise Rejected('individual/subset/modified aggregate rejected')
        tag=aggregate_tag(self.spec,messages,encode(candidate))
        self.ledger.approve(self.spec.slot,tag)
        return self.identity.sign(self.spec,'approval',dict(aggregate=tag))
    def release(self,messages,candidate,approvals):
        actual=self.recompute(messages)
        if actual!=candidate:raise Rejected('aggregate mismatch')
        tag=aggregate_tag(self.spec,messages,encode(candidate))
        items=complete(approvals,self.spec,'approval',self.roster)
        if any(v!=dict(aggregate=tag) for v in items.values()):raise Rejected('inconsistent approval')
        self.ledger.consume(self.spec.slot,tag)
        data=self.crypto.partial(candidate,self.secret,self.identity.name==self.spec.roster[0]) if self.crypto else b''
        return self.identity.sign(self.spec,'release',dict(aggregate=tag,data=encode(data)))
