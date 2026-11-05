import copy
from dataclasses import dataclass
from secure_protocol_v4.core import RoundSpec as BaseSpec,Rejected,complete,decode,encode,canonical,digest
from secure_protocol_v5.node import Node as VerifiedNode
from . import crypto as c

@dataclass(frozen=True)
class RoundSpec(BaseSpec):
    kind:str='elgamal_range'
    scale:int=65536
    bound:float=1.0
    protocol:str='v6-ristretto255-elgamal-bulletproofs'
    range_scheme:str='dalek-bulletproofs5-two-sided-pedersen-block512'
    def __post_init__(self):
        if self.kind!='elgamal_range' or self.protocol!='v6-ristretto255-elgamal-bulletproofs' or self.range_scheme!='dalek-bulletproofs5-two-sided-pedersen-block512':raise Rejected('unsupported proved protocol')
        fields=dict(self.__dict__);fields.pop('protocol');fields.pop('range_scheme');fields['kind']='he_bfv';BaseSpec(**fields)
        if self.bound*self.scale*len(self.roster)>2**29:raise Rejected('bounded decoding policy too large')

class Node(VerifiedNode):
    def contribution(self,values):
        if self.public is None or self.own is not None:raise Rejected('no verified keys/repeated contribution')
        data,proof=c.encrypt(values,self.spec,self.public,self.key_id,self.identity.name)
        self.own=self.identity.sign(self.spec,'contribution',dict(data=encode(data),range_proof=encode(proof)))
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
            if set(p)!={'data','range_proof'}:raise Rejected('mandatory range proof missing')
            data=decode(p['data']);c.verify_cipher(data,decode(p['range_proof']),self.spec,self.public,self.key_id,name);payloads.append(data)
        candidate=c.aggregate(payloads,self.spec.length);self.checked=(fingerprint,candidate)
        return candidate
