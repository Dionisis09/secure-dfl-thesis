"""Signed, context-bound messages and durable single-aggregate authorization."""
import base64
import hashlib
import json
import os
import sqlite3
import math
from dataclasses import dataclass
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives import serialization

class Rejected(ValueError): pass
def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(data): return hashlib.sha256(data).hexdigest()
def encode(data): return base64.b64encode(data).decode('ascii')
def decode(data):
    try: return base64.b64decode(data,validate=True)
    except Exception as e: raise Rejected('invalid base64') from e
def public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
@dataclass(frozen=True)
class RoundSpec:
    run: str
    epoch: str
    target: str
    round: int
    model: str
    schema: str
    roster: tuple
    length: int = 2570
    kind: str = 'he_bfv'
    scale: int = 1048576
    bound: float = 32.0
    def __post_init__(self):
        if (not all(isinstance(v,str) and v for v in [self.run,self.epoch,self.target,self.model,self.schema])
            or not math.isfinite(self.bound) or not isinstance(self.scale,int)
            or len(self.roster)<3 or len(set(self.roster))!=len(self.roster)
            or tuple(sorted(self.roster))!=self.roster or self.target not in self.roster
            or self.kind not in ('he_bfv','pairwise') or not 1<=self.length<=(4096 if self.kind=='he_bfv' else 2000000)
            or self.round<1 or self.scale<1 or self.bound<=0
            or self.bound*self.scale*len(self.roster)>=((1<<61)-1)//4):
            raise Rejected('invalid round policy')
    def body(self): return dict(self.__dict__)
    @property
    def tag(self): return digest(canonical(self.body()))
    @property
    def slot(self): return canonical([self.run,self.epoch,self.target,self.round]).decode()

class Identity:
    def __init__(self,name):
        self.name=name
        self.signing=ed25519.Ed25519PrivateKey.generate()
        self.exchange=x25519.X25519PrivateKey.generate()
    def registration(self):
        return dict(name=self.name,signing=encode(public(self.signing)),exchange=encode(public(self.exchange)))
    def sign(self,spec,phase,payload):
        body=dict(sender=self.name,context=spec.tag,phase=phase,payload=payload)
        return dict(body=body,signature=encode(self.signing.sign(canonical(body))))

def verify(message,spec,phase,roster):
    try:
        body=message['body'];sender=body['sender']
        if body['context']!=spec.tag or body['phase']!=phase or sender not in spec.roster:
            raise Rejected('wrong round/target/schema/phase/identity')
        ed25519.Ed25519PublicKey.from_public_bytes(decode(roster[sender]['signing'])).verify(
            decode(message['signature']),canonical(body))
        return sender,body['payload']
    except Rejected: raise
    except Exception as e: raise Rejected('invalid signature/envelope') from e

def complete(messages,spec,phase,roster):
    if len(messages)!=len(spec.roster): raise Rejected('missing participant')
    items={}
    for msg in messages:
        sender,payload=verify(msg,spec,phase,roster)
        if sender in items: raise Rejected('duplicate participant')
        items[sender]=payload
    if set(items)!=set(spec.roster): raise Rejected('wrong roster')
    return items

class Ledger:
    """Replay state survives process restart. Directory must be per-node private."""
    def __init__(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS approvals(slot TEXT PRIMARY KEY, hash TEXT NOT NULL, used INTEGER NOT NULL)')
        self.db.commit()
        if os.name!='nt': os.chmod(path,0o600)
    def approve(self,slot,value):
        try:
            with self.db:self.db.execute('INSERT INTO approvals VALUES(?,?,0)',(slot,value))
        except sqlite3.IntegrityError as e: raise Rejected('round already approved; rekey after abort') from e
    def consume(self,slot,value):
        with self.db:
            result=self.db.execute('UPDATE approvals SET used=1 WHERE slot=? AND hash=? AND used=0',(slot,value))
            if result.rowcount!=1: raise Rejected('unapproved or replayed release')

def aggregate_tag(spec,messages,payload):
    ordered=sorted(messages,key=lambda m:m['body']['sender'])
    return digest(canonical(dict(context=spec.tag,contributions=ordered,result=payload)))
