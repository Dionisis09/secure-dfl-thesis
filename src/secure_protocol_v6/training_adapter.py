"""Real FL-simulator boundary: HE head + full masked backbone, atomic state apply.

The existing trainer owns plaintext local states: this is not an independent-
client deployment. No plaintext update is sent through the protocol RPCs.
"""
import hashlib,time,uuid
import numpy as np
import torch
from secure_protocol_v4.core import RoundSpec as BlobSpec,canonical,digest,Rejected
from secure_protocol_v4.model_adapter import flatten,head
from .node import RoundSpec
from .transport import Group
from .chunked import aggregate_group
from .rangeproof import info

def state_hash(state):
    h=hashlib.sha256()
    for name,value in state.items():
        a=value.detach().cpu().contiguous().numpy();h.update(canonical([name,list(a.shape),str(a.dtype)]));h.update(a.tobytes())
    return h.hexdigest()
def secure_average(states,base,*,run,round_number,model_id,head_bound=1.0,backbone_bound=32.0,scale=65536,parallelism=8):
    """Return a full aggregate only after both protected segments and controls pass."""
    started=time.monotonic();native=info()
    if len(states)<3:raise Rejected('at least three peers required')
    keys=list(base)
    if any(list(s)!=keys for s in states):raise Rejected('state key mismatch')
    float_names=[name for name in keys if torch.is_floating_point(base[name])]
    head_names=['head.weight','head.bias'];backbone_names=[name for name in float_names if name not in head_names]
    if not backbone_names:raise Rejected('expected model backbone')
    deltas=[];maxima={}
    for state in states:
        delta={}
        for name,original in base.items():
            value=state[name]
            if value.shape!=original.shape or value.dtype!=original.dtype:raise Rejected('state shape/dtype mismatch')
            if torch.is_floating_point(original):
                if not torch.isfinite(value).all():raise Rejected('nonfinite trained tensor')
                delta[name]=value-original
            elif original.ndim!=0 or original.dtype==torch.bool:raise Rejected('unsupported non-floating state policy')
            else:
                number=int(value);previous=int(original)
                if number<previous:raise Rejected('integer counter decreased')
                maxima[name]=max(maxima.get(name,previous),number)
        deltas.append(delta)
    roster=tuple(f'p{i:03}' for i in range(len(states)));epoch=uuid.uuid4().hex
    hvalues={};bvalues={};reference_h=np.zeros(2570,dtype=np.int64);reference_b=None;unquant_h=np.zeros(2570);unquant_b=None
    for name,delta in zip(roster,deltas):
        hv,hschema=head(delta);bv,bschema=flatten(delta,backbone_names)
        if np.abs(hv).max()>head_bound or np.abs(bv).max()>backbone_bound:raise Rejected('trained delta exceeds configured bound; no silent clipping')
        hvalues[name]=hv;bvalues[name]=bv
        if reference_b is None:reference_b=np.zeros(len(bv),dtype=np.int64);unquant_b=np.zeros(len(bv))
        reference_h+=np.rint(hv*scale).astype(np.int64);reference_b+=np.rint(bv*scale).astype(np.int64)
        unquant_h+=hv;unquant_b+=bv
    policy=dict(base=state_hash(base),head_schema=hschema,backbone_schema=bschema,integer_maxima=maxima,weight_policy='uniform',clients=len(states),scale=scale)
    blob_spec=BlobSpec(run,epoch,roster[0],round_number,model_id,digest(canonical(policy)),roster,len(reference_b),'pairwise',scale,backbone_bound)
    backbone_start=time.monotonic()
    with Group(blob_spec,bvalues,parallelism=parallelism) as blob:
        bm,commitments=aggregate_group(blob)
        backbone_traffic=dict(request=blob.request_bytes,response=blob.response_bytes)
    backbone_seconds=time.monotonic()-backbone_start
    binding=dict(policy=policy,backbone_commitments=commitments,backbone_quantized_sum_hash=digest(np.rint(bm*len(states)*scale).astype('<i8').tobytes()))
    he_spec=RoundSpec(run,epoch,roster[0],round_number,model_id,digest(canonical(binding)),roster,2570,scale=scale,bound=head_bound)
    he_start=time.monotonic()
    with Group(he_spec,hvalues,parallelism=parallelism) as he:
        he.keygen();he.set_keys();messages=he.contributions();candidate=he.average(messages)
        approvals=he.approvals(messages,candidate);releases=he.releases(messages,candidate,approvals)
        hm=np.asarray(he.recover(messages,candidate,releases));he_traffic=dict(request=he.request_bytes,response=he.response_bytes)
    he_seconds=time.monotonic()-he_start;denominator=len(states)*scale
    hi=np.rint(hm*denominator).astype(np.int64);bi=np.rint(bm*denominator).astype(np.int64)
    if not np.array_equal(hi,reference_h) or not np.array_equal(bi,reference_b):raise Rejected('secure result differs from quantized plaintext control')
    # Apply all floating tensors and integer policies only after both protocols pass.
    # Tensor additions are performed in their original Torch dtype by apply_delta.
    def apply_delta(hdelta,bdelta):
        from secure_protocol_v4.model_adapter import restore
        overlays={**restore(hdelta,hschema),**restore(bdelta,bschema)}
        result={name:value.detach().clone() for name,value in base.items()}
        for name,array in overlays.items():result[name].add_(torch.as_tensor(array,dtype=result[name].dtype,device=result[name].device))
        for name,value in maxima.items():result[name].fill_(value)
        return result
    result=apply_delta(hm,bm);control=apply_delta(reference_h/denominator,reference_b/denominator)
    if state_hash(result)!=state_hash(control):raise Rejected('full state differs from quantized control')
    record=dict(protocol=he_spec.protocol,range_proofs_required=True,native_binary_sha256=native['binary_sha256'],clients=len(states),head_values=2570,backbone_values=len(reference_b),
        head_bound=head_bound,backbone_bound=backbone_bound,scale=scale,epoch=epoch,base_state_hash=policy['base'],model_schema_hash=digest(canonical(policy)),
        aggregate_state_hash=state_hash(result),quantized_control_state_hash=state_hash(control),quantized_control_max_integer_error=0,
        maximum_mean_quantization_error=max(float(np.max(np.abs(hm-unquant_h/len(states)))),float(np.max(np.abs(bm-unquant_b/len(states))))),
        integer_maxima=maxima,backbone_seconds=backbone_seconds,HE_seconds=he_seconds,total_aggregation_seconds=time.monotonic()-started,
        backbone_rpc_json_bytes=backbone_traffic,HE_rpc_json_bytes=he_traffic,trainer_has_plaintext_local_states=True,independent_client_isolation=False,
        scope='Real-training trusted-host simulation, full uniform topology. Range proofs cover HE head only; backbone masking has no malicious-input range proof.')
    return result,record,control
