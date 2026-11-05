"""Per-member verified HE state. No sequential mutable joint-key ceremony."""
import copy
from dataclasses import dataclass
from secure_protocol_v4.core import RoundSpec as BaseSpec,Identity,Ledger,Rejected,decode,encode,complete,verify,canonical,digest,aggregate_tag
from secure_protocol_v4.node import Node as Enrollment
from . import crypto as c

@dataclass(frozen=True)
class RoundSpec(BaseSpec):
    kind:str='elgamal_pok'
    scale:int=65536
    bound:float=1.0
    protocol:str='v5-ristretto255-elgamal-pok'
    def __post_init__(self):
        if self.kind!='elgamal_pok' or self.protocol!='v5-ristretto255-elgamal-pok':raise Rejected('unsupported protocol')
        fields=dict(self.__dict__);fields.pop('protocol');fields['kind']='he_bfv';BaseSpec(**fields)
        if self.bound*self.scale*len(self.roster)>2**29:raise Rejected('bounded decoding policy too large')

class Node:
    def __init__(self,name,spec,ledger_path):
        if name not in spec.roster:raise Rejected('unknown node')
        self.identity=Identity(name);self.spec=spec;self.ledger=Ledger(ledger_path);self.roster=None
        self.secret=None;self.key_message=None;self.public=None;self.key_id=None;self.keys=None;self.own=None;self.checked=None
    def registration(self):return self.identity.registration()
    def pin(self,roster):Enrollment.pin(self,roster)
    def keygen(self):
        if self.roster is None or self.secret is not None:raise Rejected('not enrolled/repeated keygen')
        self.secret,record=c.keygen(bytes.fromhex(self.spec.tag),self.identity.name)
        self.key_message=self.identity.sign(self.spec,'keyshare',dict(data=encode(record)))
        return copy.deepcopy(self.key_message)
    def set_keys(self,messages):
        if self.public is not None or self.key_message is None:raise Rejected('invalid/repeated key ceremony')
        items=complete(messages,self.spec,'keyshare',self.roster)
        if self.key_message not in messages:raise Rejected('own public share replaced')
        keys={}
        for name,p in items.items():
            if set(p)!={'data'}:raise Rejected('unexpected key payload')
            keys[name]=c.verify_key(bytes.fromhex(self.spec.tag),name,decode(p['data']))
        if len(set(keys.values()))!=len(keys):raise Rejected('duplicate public shares')
        joint=c.IDENTITY
        for name in self.spec.roster:joint=c.add(joint,keys[name])
        c.point(joint,True)
        self.keys=keys;self.public=joint;self.key_id=bytes.fromhex(digest(canonical(sorted(messages,key=lambda m:m['body']['sender']))))
        return encode(joint)
    def contribution(self,values):
        if self.public is None or self.own is not None:raise Rejected('no verified keys/repeated contribution')
        data=c.encrypt(values,self.spec,self.public,self.key_id,self.identity.name)
        self.own=self.identity.sign(self.spec,'contribution',dict(data=encode(data)))
        return copy.deepcopy(self.own)
    def recompute(self,messages):
        if self.public is None:raise Rejected('no verified keys')
        items=complete(messages,self.spec,'contribution',self.roster)
        if self.own is None or self.own not in messages:raise Rejected('own committed contribution missing')
        fingerprint=digest(canonical(sorted(messages,key=lambda m:m['body']['sender'])))
        if self.checked is not None and self.checked[0]==fingerprint:return self.checked[1]
        payloads=[]
        for name in self.spec.roster:
            p=items[name]
            if set(p)!={'data'}:raise Rejected('invalid contribution payload')
            data=decode(p['data']);c.verify_cipher(data,self.spec,self.public,self.key_id,name);payloads.append(data)
        candidate=c.aggregate(payloads,self.spec.length);self.checked=(fingerprint,candidate)
        return candidate
    def approve(self,messages,candidate):
        if self.recompute(messages)!=candidate:raise Rejected('individual/subset/modified aggregate rejected')
        tag=aggregate_tag(self.spec,messages,encode(candidate));self.ledger.approve(self.spec.slot,tag)
        return self.identity.sign(self.spec,'approval',dict(aggregate=tag))
    def release(self,messages,candidate,approvals):
        if self.recompute(messages)!=candidate:raise Rejected('aggregate mismatch')
        tag=aggregate_tag(self.spec,messages,encode(candidate));items=complete(approvals,self.spec,'approval',self.roster)
        if any(p!=dict(aggregate=tag) for p in items.values()):raise Rejected('inconsistent approvals')
        self.ledger.consume(self.spec.slot,tag)
        data=c.partial(candidate,self.spec,self.secret,self.keys[self.identity.name],tag,self.identity.name)
        return self.identity.sign(self.spec,'release',dict(aggregate=tag,data=encode(data)))
