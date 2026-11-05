"""Explicit tensor schema and reconstruction; no dependency on a model's layer order."""
import numpy as np
from .core import canonical,digest,Rejected

def flatten(state,names):
    arrays=[];schema=[]
    if len(set(names))!=len(names) or not names:raise Rejected('invalid tensor selection')
    for name in names:
        v=state[name]
        if hasattr(v,'detach'):v=v.detach().cpu().numpy()
        v=np.asarray(v)
        if not np.issubdtype(v.dtype,np.floating) or not np.isfinite(v).all():raise Rejected('invalid floating tensor')
        schema.append(dict(name=name,shape=list(v.shape),dtype=str(v.dtype),size=v.size));arrays.append(v.astype(np.float64).reshape(-1))
    return np.concatenate(arrays),schema
def schema_id(schema):return digest(canonical(schema))
def restore(vector,schema):
    v=np.asarray(vector,dtype=np.float64)
    if v.shape!=(sum(s['size'] for s in schema),) or not np.isfinite(v).all():raise Rejected('wrong recovered vector')
    result={};offset=0
    for s in schema:
        if np.prod(s['shape'],dtype=np.int64)!=s['size']:raise Rejected('inconsistent tensor schema')
        result[s['name']]=v[offset:offset+s['size']].reshape(s['shape']).astype(s['dtype']);offset+=s['size']
    return result
def head(state):
    names=['head.weight','head.bias'];vector,schema=flatten(state,names)
    if [s['shape'] for s in schema]!=[[10,256],[10]]:raise Rejected('expected shared256-to10 classifier')
    return vector,schema

def apply_aggregate(original,vector,schema,integer_maxima=None):
    """Return a cloned state with approved recovered tensors; preserve Torch dtype/device."""
    recovered=restore(vector,schema);result={}
    for name,value in original.items():
        result[name]=value.detach().clone() if hasattr(value,'detach') else np.array(value,copy=True)
    for name,array in recovered.items():
        if name not in result or tuple(result[name].shape)!=array.shape:raise Rejected('state/schema mismatch')
        if hasattr(result[name],'copy_'):
            import torch
            result[name].copy_(torch.as_tensor(array,device=result[name].device,dtype=result[name].dtype))
        else:result[name]=array
    for name,value in (integer_maxima or {}).items():
        if name not in result:raise Rejected('unknown integer buffer')
        original_value=result[name]
        is_float=original_value.is_floating_point() if hasattr(original_value,'is_floating_point') else np.issubdtype(original_value.dtype,np.floating)
        if is_float:raise Rejected('integer max policy cannot replace floating tensors')
        if hasattr(original_value,'fill_'):original_value.fill_(value)
        else:result[name]=np.asarray(value,dtype=original_value.dtype)
    return result
