"""Public policy and aggregate-only tensor encoding; never pickle RPC payloads."""
import hashlib
import math
import json
import os
from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path
import numpy as np
import torch
from secure_protocol_v4.core import Rejected, canonical, digest, encode, decode,complete
from secure_protocol_v4.model_adapter import flatten, restore
from secure_protocol_v4.core import RoundSpec as BlobSpec
from secure_protocol_v6.node import RoundSpec
from secure_protocol_v6.training_adapter import state_hash
from secure_protocol_v6.transport import Group


def atomic_json(path,value):
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w',encoding='utf-8') as stream:
        os.fchmod(stream.fileno(),0o600)
        json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)


@contextmanager
def run_lock(path):
    import fcntl
    with path.open('a+b') as stream:
        fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def schema_for(state):
    heads = ['head.weight', 'head.bias']
    backbone = [n for n,v in state.items() if v.is_floating_point() and n not in heads]
    hv, hs = flatten(state, heads)
    bv, bs = flatten(state, backbone)
    if len(hv) != 2570 or not len(bv):
        raise Rejected('unsupported classifier/backbone')
    return hs, bs


def encode_state(state):
    return encode(b''.join(v.detach().cpu().contiguous().numpy().tobytes() for v in state.values()))


def decode_state(value, template):
    raw = decode(value)
    expected = sum(v.numel()*v.element_size() for v in template.values())
    if len(raw) != expected:
        raise Rejected('wrong aggregate-state byte count')
    result = {}; offset = 0
    for name, value in template.items():
        a = value.detach().cpu().numpy(); size = a.nbytes
        array = np.frombuffer(raw[offset:offset+size],dtype=a.dtype).reshape(a.shape).copy()
        if np.issubdtype(array.dtype,np.floating) and not np.isfinite(array).all():
            raise Rejected('nonfinite aggregate state')
        result[name] = torch.from_numpy(array); offset += size
    return result


def policy(job, base):
    hs, bs = schema_for(base)
    steps = max(math.ceil(n/job['batch_size'])*job['local_epochs'] for n in job['partition_sizes'])
    counters = {}
    for name,value in base.items():
        if not value.is_floating_point():
            if value.ndim != 0 or value.dtype != torch.int64 or not name.endswith('.num_batches_tracked'):
                raise Rejected('unsupported integer buffer')
            counters[name] = int(value)+steps
    return dict(job=job['job_id'],base=state_hash(base),head_schema=hs,backbone_schema=bs,
                integer_maxima=counters,weight_policy='uniform',clients=len(job['roster']),scale=job['scale'])


def blob_spec(job, base, number, epoch):
    p = policy(job,base)
    return BlobSpec(job['job_id'],epoch,job['roster'][0],number,job['model'],
                    digest(canonical(p)),tuple(job['roster']),sum(s['size'] for s in p['backbone_schema']),
                    'pairwise',job['scale'],job['backbone_bound'])


def round_enrollment(job,base,number,epoch,messages):
    preliminary=blob_spec(job,base,number,epoch)
    items=complete(messages,preliminary,'trained',job['enrollment'])
    roster={}
    expected=dict(base=state_hash(base),round=number,policy=preliminary.schema)
    for name,payload in items.items():
        if set(payload)!=set(expected)|{'exchange'} or any(payload[k]!=v for k,v in expected.items()):
            raise Rejected('round training/enrollment mismatch')
        if len(decode(payload['exchange']))!=32:raise Rejected('invalid ephemeral exchange key')
        roster[name]=dict(job['enrollment'][name],exchange=payload['exchange'])
    spec=replace(preliminary,schema=digest(canonical(dict(training_policy=preliminary.schema,ephemeral_enrollment=roster))))
    return roster,spec


def he_spec(job, base, number, epoch, commitments, backbone_mean,round_roster):
    total = np.rint(backbone_mean*len(job['roster'])*job['scale']).astype('<i8')
    binding = dict(policy=policy(job,base),ephemeral_enrollment=round_roster,backbone_commitments=commitments,
                   backbone_quantized_sum_hash=digest(total.tobytes()))
    return RoundSpec(job['job_id'],epoch,job['roster'][0],number,job['model'],
                     digest(canonical(binding)),tuple(job['roster']),2570,
                     scale=job['scale'],bound=job['head_bound'])


def apply_aggregate(job, base, head_mean, backbone_mean):
    p = policy(job,base)
    values = {**restore(head_mean,p['head_schema']),**restore(backbone_mean,p['backbone_schema'])}
    result = {n:v.clone() for n,v in base.items()}
    for name,array in values.items():
        result[name].add_(torch.as_tensor(array,dtype=result[name].dtype))
    for name,value in p['integer_maxima'].items():
        result[name].fill_(value)
    return result


class HEView:
    """Verifier only: public transcript, no fixture/process creation/private values."""
    average = Group.average
    recover = Group.recover
    def __init__(self,spec,roster,keys,parallelism=4):
        self.spec=spec;self.roster=roster;self.keys=keys;self.parallelism=parallelism


def code_hash():
    root = Path(__file__).resolve().parents[2]
    files = sorted((root/'src').rglob('*.py')) + [root/'scripts/independent_client.py',root/'scripts/run_independent_training.py']
    return digest(canonical({p.relative_to(root).as_posix():digest(p.read_text(encoding='utf-8').encode()) for p in files}))


def validate_job(job):
    content = {k:v for k,v in job.items() if k!='job_id'}
    if digest(canonical(content)) != job.get('job_id'):
        raise Rejected('job policy hash mismatch')
    roster = job['roster']
    if job['version'] != 7 or job['topology'] != 'full' or job['weights'] != 'uniform':
        raise Rejected('unsupported independent-client policy')
    if job['model'] not in ('mlp','cnn') or job['input_shape'] not in ([3,32,32],[1,28,28]):
        raise Rejected('unsupported model/input policy')
    if not 3<=len(roster)<=50 or list(sorted(set(roster)))!=roster:
        raise Rejected('invalid roster')
    if len(job['partition_sizes'])!=len(roster) or any(type(n)!=int or n<2 for n in job['partition_sizes']):
        raise Rejected('invalid sample-size policy')
    if not (type(job['rounds'])==int and 1<=job['rounds']<=10000 and
            type(job['batch_size'])==int and 2<=job['batch_size']<=4096 and
            type(job['local_epochs'])==int and 1<=job['local_epochs']<=100 and
            0<job['learning_rate']<1 and job['scale']==65536 and
            job['backbone_bound']==32. and 0<job['head_bound']<=1.):
        raise Rejected('invalid fixed training policy')
    if job['source_hash'] != code_hash():
        raise Rejected('source changed after enrollment')
    if set(job['enrollment']) != set(roster):
        raise Rejected('incomplete enrollment')
    return job
