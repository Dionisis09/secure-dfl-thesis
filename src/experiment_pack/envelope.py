"""Signed ephemeral E2E envelopes: the relay cannot read peer application data."""
import os
from cryptography.hazmat.primitives.asymmetric import x25519,ed25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from secure_protocol_v4.core import canonical,digest,encode,decode,Rejected
import json

def key(identity,other,roster,context):
    shared=identity.exchange.exchange(x25519.X25519PublicKey.from_public_bytes(decode(roster[other]['exchange'])))
    return HKDF(algorithm=hashes.SHA256(),length=32,salt=bytes.fromhex(context),info=canonical(['v8-e2e',sorted([identity.name,other])])).derive(shared)

def seal(identity,recipient,roster,context,label,payload):
    header=dict(sender=identity.name,recipient=recipient,context=context,label=label)
    nonce=os.urandom(12);cipher=ChaCha20Poly1305(key(identity,recipient,roster,context)).encrypt(nonce,canonical(payload),canonical(header))
    body=dict(**header,nonce=encode(nonce),ciphertext=encode(cipher))
    return dict(body=body,signature=encode(identity.signing.sign(canonical(body))))

def open_envelope(identity,sender,roster,context,label,message):
    try:
        body=message['body'];header={k:body[k] for k in ('sender','recipient','context','label')}
        if header!=dict(sender=sender,recipient=identity.name,context=context,label=label) or set(body)!=set(header)|{'nonce','ciphertext'}:raise Rejected('wrong sealed context')
        ed25519.Ed25519PublicKey.from_public_bytes(decode(roster[sender]['signing'])).verify(decode(message['signature']),canonical(body))
        raw=ChaCha20Poly1305(key(identity,sender,roster,context)).decrypt(decode(body['nonce']),decode(body['ciphertext']),canonical(header))
        from secure_protocol_v4.transport import strict_object,reject_constant
        return json.loads(raw,object_pairs_hook=strict_object,parse_constant=reject_constant)
    except Rejected:raise
    except Exception as error:raise Rejected('sealed peer message rejected') from error
