"""Ciphertext/independent-Pedersen equality proof + mandatory two-sided Bulletproof."""
from secure_protocol_v5.crypto import *
from secure_protocol_v5 import crypto as ec
from . import rangeproof as rp

def pedersen_h():
    metadata=rp.info();H=bytes.fromhex(metadata['h']);point(H,True)
    if bytes.fromhex(metadata['generator'])!=base(scalar(1)):raise Rejected('native group mismatch')
    return H
def range_context(data,spec,key_id,owner):
    from secure_protocol_v4.core import canonical,digest
    return bytes.fromhex(digest(canonical(dict(protocol=spec.protocol,context=spec.tag,key=key_id.hex(),owner=owner,data_hash=digest(data),bound=rp.bound_integer(spec),bits=rp.range_bits(spec)))))
def _encrypt_records(integers,spec,public,key_id,owner):
    """Local encoder; separate so adversarial tests can construct valid outside-range PoKs."""
    H=pedersen_h();out=[];blindings=[];prefix=bytes.fromhex(spec.tag)+key_id+owner.encode()
    for i,value in enumerate(integers):
        m=scalar(value);r=random_scalar();b=random_scalar();a=random_scalar();d=random_scalar();e=random_scalar()
        R=base(r);C=add(base(m),mul(r,public));V=add(base(m),mul(b,H))
        T1=base(a);T2=add(base(d),mul(a,public));T3=add(base(d),mul(e,H))
        k=challenge(b'bounded-cipher-pok',prefix,i.to_bytes(4,'big'),public,H,R,C,V,T1,T2,T3)
        out.append(R+C+V+T1+T2+T3+sa(a,sm(k,r))+sa(d,sm(k,m))+sa(e,sm(k,b)));blindings.append(b)
    return b''.join(out),blindings
def encrypt(values,spec,public,key_id,owner):
    v=np.asarray(values,dtype=np.float64)
    if v.shape!=(spec.length,) or not np.isfinite(v).all() or np.abs(v).max()>spec.bound:raise Rejected('invalid input/bound')
    integers=np.rint(v*spec.scale).astype(np.int64)
    data,blindings=_encrypt_records(integers,spec,public,key_id,owner)
    proof=rp.prove(integers,blindings,spec,range_context(data,spec,key_id,owner))
    return data,proof
def verify_cipher(data,proof,spec,public,key_id,owner):
    H=pedersen_h();prefix=bytes.fromhex(spec.tag)+key_id+owner.encode();commitments=[]
    for i,(R,C,V,T1,T2,T3,zr,zm,zb) in chunks(data,288,spec.length):
        point(R,True)
        for p in (C,V,T1,T2,T3):point(p)
        for z in (zr,zm,zb):response(z)
        k=challenge(b'bounded-cipher-pok',prefix,i.to_bytes(4,'big'),public,H,R,C,V,T1,T2,T3)
        if base(zr)!=add(T1,mul(k,R)) or add(base(zm),mul(zr,public))!=add(T2,mul(k,C)) or add(base(zm),mul(zb,H))!=add(T3,mul(k,V)):
            raise Rejected('bounded ciphertext knowledge proof rejected')
        commitments.append(V)
    rp.verify(commitments,proof,spec,range_context(data,spec,key_id,owner))
def aggregate(payloads,length):
    total=[(IDENTITY,IDENTITY) for _ in range(length)]
    for data in payloads:
        for i,record in chunks(data,288,length):total[i]=(add(total[i][0],record[0]),add(total[i][1],record[1]))
    return b''.join(R+C for R,C in total)
