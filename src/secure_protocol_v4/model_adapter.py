"""Explicit tensor schema and reconstruction; no dependency on a model's layer order."""
import numpy as np
import math
from .core import canonical,digest,Rejected

def validate_schema(schema):
    if not isinstance(schema,list) or not schema:raise Rejected('invalid tensor schema')
    names=set();total=0
    for s in schema:
        if not isinstance(s,dict) or set(s)!={'name','shape','dtype','size'}:raise Rejected('invalid tensor schema')
        if not isinstance(s['name'],str) or not s['name'] or s['name'] in names:raise Rejected('duplicate/invalid tensor name')
        shape=s['shape']
        if not isinstance(shape,list) or len(shape)>16 or any(type(d) is not int or not 0<=d<=2000000 for d in shape):raise Rejected('invalid tensor shape')
        if type(s['size']) is not int or math.prod(shape)!=s['size'] or s['size']<1:raise Rejected('inconsistent tensor size')
        if s['dtype'] not in ('float16','float32','float64'):raise Rejected('unsupported tensor dtype')
        names.add(s['name']);total+=s['size']
        if total>2000000:raise Rejected('tensor schema too large')
    return total

def flatten(state,names):
    arrays=[];schema=[]
    if len(set(names))!=len(names) or not names:raise Rejected('invalid tensor selection')
    for name in names:
        v=state[name]
        if hasattr(v,'detach'):v=v.detach().cpu().numpy()
        v=np.asarray(v)
        if not np.issubdtype(v.dtype,np.floating) or not np.isfinite(v).all():raise Rejected('invalid floating tensor')
        schema.append(dict(name=name,shape=list(v.shape),dtype=str(v.dtype),size=v.size));arrays.append(v.astype(np.float64).reshape(-1))
    validate_schema(schema)
    return np.concatenate(arrays),schema
def schema_id(schema):
    validate_schema(schema)
    return digest(canonical(schema))
def restore(vector,schema):
    total=validate_schema(schema)
    v=np.asarray(vector,dtype=np.float64)
    if v.shape!=(total,) or not np.isfinite(v).all():raise Rejected('wrong recovered vector')
    result={};offset=0
    for s in schema:
        with np.errstate(over='ignore',invalid='ignore'):
            array=v[offset:offset+s['size']].reshape(s['shape']).astype(s['dtype'])
        if not np.isfinite(array).all():raise Rejected('recovered tensor overflows destination dtype')
        result[s['name']]=array;offset+=s['size']
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
        destination=result[name]
        dtype=str(destination.detach().cpu().numpy().dtype) if hasattr(destination,'detach') else str(destination.dtype)
        if dtype!=str(array.dtype):raise Rejected('state/schema dtype mismatch')
        if hasattr(result[name],'copy_'):
            import torch
            result[name].copy_(torch.as_tensor(array,device=result[name].device,dtype=result[name].dtype))
        else:result[name]=array
    for name,value in (integer_maxima or {}).items():
        if name not in result:raise Rejected('unknown integer buffer')
        original_value=result[name]
        array=original_value.detach().cpu().numpy() if hasattr(original_value,'detach') else original_value
        if array.shape!=() or not np.issubdtype(array.dtype,np.integer):raise Rejected('integer max policy requires scalar integer buffer')
        if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,np.integer)):raise Rejected('integer buffer requires exact integer')
        limits=np.iinfo(array.dtype)
        if not limits.min<=value<=limits.max or value<int(array):raise Rejected('invalid integer maximum')
        if hasattr(original_value,'fill_'):original_value.fill_(value)
        else:result[name]=np.asarray(value,dtype=original_value.dtype)
    return result
