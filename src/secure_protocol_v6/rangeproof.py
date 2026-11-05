"""Fail-closed C ABI to Dalek Bulletproofs. Private witnesses stay in local memory."""
import ctypes,functools,hashlib,json,math,os,sys,struct
from pathlib import Path
from secure_protocol_v4.core import Rejected

def bound_integer(spec):return math.ceil(spec.bound*spec.scale)
def range_bits(spec):
    limit=2*bound_integer(spec)
    return next(n for n in (8,16,32) if limit<2**n)

@functools.lru_cache(maxsize=1)
def backend():
    name='dfl_range.dll' if sys.platform=='win32' else ('libdfl_range.dylib' if sys.platform=='darwin' else 'libdfl_range.so')
    path=Path(os.environ.get('DFL_RANGE_LIB',str(Path(__file__).resolve().parents[2]/'native/dfl_range/target/release'/name))).resolve()
    if not path.is_file():raise Rejected('Native Bulletproofs backend missing; build native/dfl_range. No unproved fallback.')
    lib=ctypes.CDLL(str(path));lib.dfl_range_call.argtypes=[ctypes.c_char_p];lib.dfl_range_call.restype=ctypes.c_void_p
    lib.dfl_range_free.argtypes=[ctypes.c_void_p];lib.dfl_range_free.restype=None
    return lib,path
def call(request):
    lib,_=backend();raw=json.dumps(request,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>4*1024*1024:raise Rejected('range request too large')
    pointer=lib.dfl_range_call(raw)
    if not pointer:raise Rejected('range backend failed')
    try:result=json.loads(ctypes.string_at(pointer))
    finally:lib.dfl_range_free(pointer)
    if not result.get('ok'):raise Rejected('range proof rejected')
    return result
@functools.lru_cache(maxsize=1)
def info():
    result=call({'op':'info'});_,path=backend()
    result.update(binary_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return result
BLOCK=512
def block_context(context,index,count):return hashlib.sha256(context+struct.pack('>II',index,count)).hexdigest()
def prove(integers,blindings,spec,context):
    blocks=[]
    for index,start in enumerate(range(0,len(integers),BLOCK)):
        values=integers[start:start+BLOCK];randomness=blindings[start:start+BLOCK]
        result=call(dict(op='prove',bound=bound_integer(spec),bits=range_bits(spec),context=block_context(context,index,len(values)),values=[int(m) for m in values],blindings=[b.hex() for b in randomness]))
        proof=bytes.fromhex(result['proof']);blocks.append(struct.pack('>H',len(proof))+proof)
    return b'R6BP'+struct.pack('>HH',BLOCK,len(blocks))+b''.join(blocks)
def verify(commitments,proof,spec,context):
    if not isinstance(proof,bytes) or not 0<len(proof)<=16384:raise Rejected('invalid range proof length')
    count=math.ceil(len(commitments)/BLOCK)
    if len(proof)<8 or proof[:8]!=b'R6BP'+struct.pack('>HH',BLOCK,count):raise Rejected('invalid range-proof framing')
    offset=8
    for index,start in enumerate(range(0,len(commitments),BLOCK)):
        if offset+2>len(proof):raise Rejected('truncated range proof')
        size=struct.unpack('>H',proof[offset:offset+2])[0];offset+=2
        if not size or offset+size>len(proof):raise Rejected('truncated range proof')
        group=commitments[start:start+BLOCK]
        call(dict(op='verify',bound=bound_integer(spec),bits=range_bits(spec),context=block_context(context,index,len(group)),commitments=[p.hex() for p in group],proof=proof[offset:offset+size].hex()))
        offset+=size
    if offset!=len(proof):raise Rejected('trailing range-proof data')
