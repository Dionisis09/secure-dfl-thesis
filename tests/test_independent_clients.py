import copy
import json
import os
from pathlib import Path
import sys
import unittest
import subprocess
import tempfile
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from independent_clients.common import encode_state,decode_state,apply_aggregate,schema_for,policy
from independent_clients.service import ClientService
from secure_protocol_v4.core import Rejected
from secure_protocol_v6.training_adapter import state_hash
from matched_models import build_model


class IndependentClientTests(unittest.TestCase):
    def test_aggregate_wire_exact_and_rejects_trailing_bytes(self):
        template={'features.weight':torch.ones(2,3),'counter':torch.tensor(4,dtype=torch.int64)}
        self.assertEqual(state_hash(template),state_hash(decode_state(encode_state(template),template)))
        from secure_protocol_v4.core import encode,decode
        with self.assertRaises(Rejected):decode_state(encode(decode(encode_state(template))+b'x'),template)
        broken=copy.deepcopy(template);broken['features.weight'][0,0]=float('nan')
        with self.assertRaises(Rejected):decode_state(encode_state(broken),template)

    def test_no_plaintext_model_or_remote_path_api(self):
        service=ClientService.__new__(ClientService)
        for op in ['get_state','get_optimizer','debug','test_forge','load','save','eval','export','upload','get_local_model']:
            with self.assertRaises(Rejected):service.rpc(op,{})
        with self.assertRaises(Rejected):service.rpc('train',dict(round=1,epoch='0'*32,base='x',path='/etc/passwd'))

    def test_integer_counters_have_public_fixed_policy(self):
        torch.set_num_threads(1);model=build_model('cnn',(3,32,32));base=model.state_dict()
        job=dict(job_id='fixed',batch_size=16,local_epochs=2,partition_sizes=[32,48,64],roster=['p000','p001','p002'],scale=65536)
        p=policy(job,base)
        self.assertEqual(set(p['integer_maxima'].values()),{8})
        hs,bs=schema_for(base)
        result=apply_aggregate(job,base,np.zeros(sum(s['size'] for s in hs)),np.zeros(sum(s['size'] for s in bs)))
        for name,value in result.items():
            if name in p['integer_maxima']:self.assertEqual(int(value),8)
            else:torch.testing.assert_close(value,base[name],rtol=0,atol=0)

    def test_coordinator_checkpoint_and_rpc_code_has_no_local_training(self):
        import ast
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'src/independent_clients/coordinator.py').read_text())
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
        forbidden={'Client','PrivateImages','secure_average','torch.load','train_local'}
        def name(node):
            if isinstance(node,ast.Name):return node.id
            if isinstance(node,ast.Attribute):return name(node.value)+'.'+node.attr
            return ''
        self.assertFalse({name(n.func) for n in calls}&forbidden)
        self.assertFalse(any(isinstance(n,ast.ImportFrom) and n.module in ('client','secure_training') for n in ast.walk(tree)))

    def test_ephemeral_enrollment_rejects_replay_substitution_and_omission(self):
        from secure_protocol_v4.core import Identity
        from independent_clients.common import blob_spec,round_enrollment
        torch.manual_seed(7);base=build_model('mlp',(3,32,32)).state_dict()
        peers={n:Identity(n) for n in ['p000','p001','p002']}
        job=dict(job_id='test-job',batch_size=16,local_epochs=1,partition_sizes=[32]*3,
            roster=list(peers),enrollment={n:i.registration() for n,i in peers.items()},model='mlp',scale=65536,backbone_bound=32.)
        spec=blob_spec(job,base,1,'a'*32)
        messages=[i.sign(spec,'trained',dict(base=state_hash(base),round=1,policy=spec.schema,exchange=Identity(n).registration()['exchange'])) for n,i in peers.items()]
        roster,bound=round_enrollment(job,base,1,'a'*32,messages)
        self.assertNotEqual(spec.tag,bound.tag)
        self.assertEqual(set(roster),set(peers))
        for changed in [messages[:-1],messages[:2]+[messages[0]]]:
            with self.assertRaises(Rejected):round_enrollment(job,base,1,'a'*32,changed)
        altered=copy.deepcopy(messages);altered[0]['body']['payload']['exchange']=peers['p001'].registration()['exchange']
        with self.assertRaises(Rejected):round_enrollment(job,base,1,'a'*32,altered)
        with self.assertRaises(Rejected):round_enrollment(job,base,2,'a'*32,messages)

    @unittest.skipUnless(sys.platform=='linux','Linux Landlock required')
    def test_real_filesystem_denial_including_future_thread(self):
        source=str(Path(__file__).resolve().parents[1]/'src')
        code='''
import json,sys,threading,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from independent_clients.isolation import restrict_files
own=Path(sys.argv[2]);foreign=Path(sys.argv[3]);outcomes=[]
result=restrict_files(own)
assert (own/'own').read_text()=='allowed'
def probe():
    try:foreign.read_bytes()
    except PermissionError:outcomes.append(True)
    else:raise RuntimeError('foreign private file readable')
probe();thread=threading.Thread(target=probe);thread.start();thread.join()
assert outcomes==[True,True]
try:os.chmod(foreign,0o777)
except PermissionError:pass
else:raise RuntimeError('foreign permission change accepted')
print(json.dumps(dict(enforced=True,future_thread_inherits=True)))
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);own=root/'own';own.mkdir();(own/'own').write_text('allowed');foreign=root/'foreign';foreign.write_text('private')
            result=subprocess.run([sys.executable,'-c',code,source,str(own),str(foreign)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads(result.stdout)['future_thread_inherits'])

    @unittest.skipUnless(sys.platform=='linux','Linux Landlock required')
    def test_preexisting_thread_fails_closed(self):
        source=str(Path(__file__).resolve().parents[1]/'src')
        code='''
import sys,threading
sys.path.insert(0,sys.argv[1])
from independent_clients.isolation import restrict_files
stop=threading.Event();thread=threading.Thread(target=stop.wait);thread.start()
try:
    try:restrict_files(sys.argv[2])
    except RuntimeError as error:assert 'single-threaded' in str(error)
    else:raise AssertionError('multithreaded startup accepted')
finally:stop.set();thread.join()
'''
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,'-c',code,source,directory],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(sys.platform=='linux','Linux Landlock and seccomp required')
    def test_local_control_plane_and_unenrolled_network_fail_closed(self):
        import socket
        source=str(Path(__file__).resolve().parents[1]/'src')
        code='''
import sys,json,socket,ctypes,errno
sys.path.insert(0,sys.argv[1])
from independent_clients.isolation import restrict_files
port=int(sys.argv[3]);restrict_files(sys.argv[2],connect_ports=[port])
for family,kind in [(socket.AF_UNIX,socket.SOCK_STREAM),(socket.AF_INET,socket.SOCK_DGRAM),(socket.AF_NETLINK,socket.SOCK_RAW)]:
    try:socket.socket(family,kind)
    except PermissionError:pass
    else:raise RuntimeError('forbidden socket domain/type accepted')
try:socket.socketpair()
except PermissionError:pass
else:raise RuntimeError('socketpair accepted')
with socket.socket() as sock:
    try:sock.connect(('127.0.0.1',22))
    except PermissionError:pass
    else:raise RuntimeError('non-enrolled TCP port accepted')
with socket.create_connection(('127.0.0.1',port)) as sock:sock.sendall(b'allowed')
libc=ctypes.CDLL(None,use_errno=True);ctypes.set_errno(0)
assert libc.syscall(425,1,0)==-1 and ctypes.get_errno()==errno.EPERM
print(json.dumps(dict(unix_ipc_denied=True,non_enrolled_tcp_denied=True,enrolled_tcp_works=True,io_uring_denied=True)))
'''
        with tempfile.TemporaryDirectory() as directory,socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen(1)
            result=subprocess.run([sys.executable,'-c',code,source,directory,str(listener.getsockname()[1])],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads(result.stdout)['enrolled_tcp_works'])


if __name__=='__main__':unittest.main()
