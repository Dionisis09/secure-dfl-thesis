"""Ristretto255 exponential ElGamal with domain-separated Fiat-Shamir proofs.

Schnorr key-share possession; AND representation proof for (r,m) in each
ciphertext; Chaum-Pedersen equality-of-log proof for each decryption share.
Uses native libsodium through rbcl. No home-grown curve arithmetic.
"""
import hashlib,math
import numpy as np
import rbcl as s
from secure_protocol_v4.core import Rejected

ORDER=2**252+27742317777372353535851937790883648493
ZERO=bytes(32)
IDENTITY=bytes(32)  # Ristretto encoding (not Edwards encoding).
add=s.crypto_core_ristretto255_add
sub=s.crypto_core_ristretto255_sub
sa=s.crypto_core_ristretto255_scalar_add
sm=s.crypto_core_ristretto255_scalar_mul

def scalar(n):return (int(n)%ORDER).to_bytes(32,'little')
def random_scalar():
    while True:
        value=s.crypto_core_ristretto255_scalar_random()
        if value!=ZERO:return value
def base(k):return IDENTITY if k==ZERO else s.crypto_scalarmult_ristretto255_base(k)
def mul(k,p):return IDENTITY if k==ZERO or p==IDENTITY else s.crypto_scalarmult_ristretto255(k,p)
def point(p,nonzero=False):
    if not isinstance(p,bytes) or len(p)!=32 or not s.crypto_core_ristretto255_is_valid_point(p) or (nonzero and p==IDENTITY):
        raise Rejected('invalid/noncanonical group element')
    return p
def response(z):
    if len(z)!=32 or int.from_bytes(z,'little')>=ORDER:raise Rejected('noncanonical scalar')
    return z
def challenge(domain,*parts):
    h=hashlib.sha512(b'secure-dfl-v5/'+domain)
    for part in parts:h.update(len(part).to_bytes(8,'big'));h.update(part)
    return s.crypto_core_ristretto255_scalar_reduce(h.digest())
def chunks(data,width,length):
    if not isinstance(data,bytes) or len(data)!=width*length:raise Rejected('invalid proof vector length')
    for i in range(length):yield i,tuple(data[i*width+j:i*width+j+32] for j in range(0,width,32))

def keygen(context,owner):
    secret=random_scalar();public=base(secret);nonce=random_scalar();commit=base(nonce)
    c=challenge(b'key-pop',context,owner.encode(),public,commit)
    return secret,public+commit+sa(nonce,sm(c,secret))
def verify_key(context,owner,record):
    if len(record)!=96:raise Rejected('invalid key proof length')
    public,commit,z=record[:32],record[32:64],record[64:]
    point(public,True);point(commit);response(z)
    c=challenge(b'key-pop',context,owner.encode(),public,commit)
    if base(z)!=add(commit,mul(c,public)):raise Rejected('key proof of possession rejected')
    return public

def encrypt(values,spec,public,key_id,owner):
    v=np.asarray(values,dtype=np.float64)
    if v.shape!=(spec.length,) or not np.isfinite(v).all() or np.abs(v).max()>spec.bound:raise Rejected('invalid input/bound')
    integers=np.rint(v*spec.scale).astype(np.int64);out=[]
    prefix=bytes.fromhex(spec.tag)+key_id+owner.encode()
    for i,value in enumerate(integers):
        m=scalar(value);r=random_scalar();a=random_scalar();b=random_scalar()
        R=base(r);C=add(base(m),mul(r,public));T1=base(a);T2=add(base(b),mul(a,public))
        c=challenge(b'cipher-pok',prefix,i.to_bytes(4,'big'),public,R,C,T1,T2)
        out.append(R+C+T1+T2+sa(a,sm(c,r))+sa(b,sm(c,m)))
    return b''.join(out)
def verify_cipher(data,spec,public,key_id,owner):
    prefix=bytes.fromhex(spec.tag)+key_id+owner.encode()
    for i,(R,C,T1,T2,zr,zm) in chunks(data,192,spec.length):
        point(R,True);point(C);point(T1);point(T2);response(zr);response(zm)
        c=challenge(b'cipher-pok',prefix,i.to_bytes(4,'big'),public,R,C,T1,T2)
        if base(zr)!=add(T1,mul(c,R)) or add(base(zm),mul(zr,public))!=add(T2,mul(c,C)):
            raise Rejected('ciphertext knowledge proof rejected')
def aggregate(payloads,length):
    total=[(IDENTITY,IDENTITY) for _ in range(length)]
    for data in payloads:
        for i,record in chunks(data,192,length):total[i]=(add(total[i][0],record[0]),add(total[i][1],record[1]))
    return b''.join(R+C for R,C in total)
def partial(candidate,spec,secret,public,tag,owner):
    out=[];prefix=bytes.fromhex(spec.tag)+bytes.fromhex(tag)+owner.encode()
    for i,(R,C) in chunks(candidate,64,spec.length):
        point(R);point(C);D=mul(secret,R);a=random_scalar();T1=base(a);T2=mul(a,R)
        c=challenge(b'decrypt-dleq',prefix,i.to_bytes(4,'big'),public,R,C,D,T1,T2)
        out.append(D+T1+T2+sa(a,sm(c,secret)))
    return b''.join(out)
def verify_partial(data,candidate,spec,public,tag,owner):
    prefix=bytes.fromhex(spec.tag)+bytes.fromhex(tag)+owner.encode();result=[]
    for (i,(D,T1,T2,z)),(_,(R,C)) in zip(chunks(data,128,spec.length),chunks(candidate,64,spec.length)):
        point(D);point(T1);point(T2);response(z)
        c=challenge(b'decrypt-dleq',prefix,i.to_bytes(4,'big'),public,R,C,D,T1,T2)
        if base(z)!=add(T1,mul(c,public)) or mul(z,R)!=add(T2,mul(c,D)):
            raise Rejected('decryption share proof rejected')
        result.append(D)
    return result

class BoundedLog:
    """Exact signed bounded discrete log; public aggregate only, not secret inputs."""
    def __init__(self,bound):
        self.bound=int(bound);self.width=math.isqrt(2*self.bound+1)+1
        self.table={};p=IDENTITY;G=base(scalar(1))
        for j in range(self.width):self.table[p]=j;p=add(p,G)
        self.step=base(scalar(self.width));self.cache={}
    def decode(self,p):
        point(p)
        if p in self.cache:return self.cache[p]
        positive=negative=p
        for i in range(self.bound//self.width+2):
            for current,sign in ((positive,1),(negative,-1)):
                if current in self.table:
                    value=sign*i*self.width+self.table[current]
                    if abs(value)<=self.bound:self.cache[p]=value;return value
            positive=sub(positive,self.step);negative=add(negative,self.step)
        raise Rejected('aggregate outside decodable range; abort, no plaintext fallback')
