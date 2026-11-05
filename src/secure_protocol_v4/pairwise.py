"""Authenticated ephemeral ECDH -> HKDF -> ChaCha20 uniform finite-field masks."""
import numpy as np
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms
from .core import Rejected,canonical,decode
Q=(1<<61)-1

def quantize(values,spec):
    v=np.asarray(values,dtype=np.float64)
    if v.shape!=(spec.length,) or not np.isfinite(v).all() or np.abs(v).max()>spec.bound:
        raise Rejected('shape/nonfinite/bound violation; no silent clipping')
    return np.mod(np.rint(v*spec.scale).astype(np.int64),Q)
def pack(values): return np.asarray(values,dtype='<i8').tobytes()
def unpack(data,spec):
    if len(data)!=8*spec.length: raise Rejected('wrong modular vector size')
    v=np.frombuffer(data,dtype='<i8').copy()
    if np.any(v<0) or np.any(v>=Q): raise Rejected('noncanonical field element')
    return v
def mask(identity,other,spec,roster):
    pair=sorted([identity.name,other])
    shared=identity.exchange.exchange(x25519.X25519PublicKey.from_public_bytes(decode(roster[other]['exchange'])))
    key=HKDF(algorithm=hashes.SHA256(),length=32,salt=bytes.fromhex(spec.tag),info=canonical(['mask-v4',pair])).derive(shared)
    stream=Cipher(algorithms.ChaCha20(key,b'\0'*16),mode=None).encryptor()
    # Exact rejection sampling, not a biased reduction of arbitrary uint64 words.
    cutoff=np.uint64(8*Q);accepted=[];count=0
    while count<spec.length:
        words=np.frombuffer(stream.update(b'\0'*(8*(spec.length-count+8))),dtype='<u8')
        words=(words[words<cutoff]%np.uint64(Q)).astype(np.int64)
        accepted.append(words);count+=len(words)
    return np.concatenate(accepted)[:spec.length]
def protect(identity,values,spec,roster):
    result=quantize(values,spec)
    for other in spec.roster:
        if other==identity.name: continue
        m=mask(identity,other,spec,roster)
        result=np.mod(result+m if identity.name<other else result-m,Q)
    return pack(result)
def sum_vectors(payloads,spec):
    total=np.zeros(spec.length,dtype=np.int64)
    for payload in payloads: total=np.mod(total+unpack(payload,spec),Q)
    return pack(total)
def recover(payload,spec):
    v=unpack(payload,spec);v=np.where(v>Q//2,v-Q,v)
    if np.abs(v).max()>spec.bound*spec.scale*len(spec.roster)+len(spec.roster):
        raise Rejected('aggregate outside declared range')
    return v.astype(np.float64)/(spec.scale*len(spec.roster))
