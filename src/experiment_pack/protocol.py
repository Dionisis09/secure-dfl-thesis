"""Public control messages and routing schedule, with no training/model objects."""
import math
from secure_protocol_v4.core import RoundSpec,verify,Rejected
from secure_protocol_v6.chunked import CHUNK_VALUES

def control(job,number,epoch):
    roster=tuple(job['roster'])
    return RoundSpec(job['job_id'],epoch,roster[0],number,job['config']['model'],job['job_id'],roster,1,'pairwise',65536,32.)

def signed_subset(messages,spec,phase,enrollment,names):
    result={}
    for message in messages:
        name,payload=verify(message,spec,phase,enrollment)
        if name in result:raise Rejected('duplicate signer')
        result[name]=payload
    if set(result)!=set(names):raise Rejected('missing/wrong signers')
    return result

def local_counters(job,number):
    counts={n:0 for n in job['roster']};graph=job['adjacency'];cfg=job['config']
    steps={n:math.ceil(size/cfg['batch_size'])*cfg['local_epochs'] for n,size in zip(job['roster'],job['partition_sizes'])}
    for _ in range(number-1):counts={n:max(counts[x]+steps[x] for x in [n,*graph[n]]) for n in counts}
    return {n:counts[n]+steps[n] for n in counts}

def phases(session_length,split):
    yield 'blob_commit',0,True
    yield 'blob_begin',0,False
    for index in range(math.ceil(session_length/CHUNK_VALUES)):
        yield 'blob_chunk',index,True
        yield 'blob_accept',index,False
    yield 'blob_approval',0,True
    yield 'blob_release',0,True
    yield 'blob_finish',0,False
    if split:
        for name,route in [('he_init',False),('he_key',True),('he_set_keys',False),('he_contribution',True),('he_approval',True),('he_release',True),('he_finish',False)]:yield name,0,route
