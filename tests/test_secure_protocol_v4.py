import dataclasses,json,sys,tempfile,unittest,copy,socket,ssl,time,http.client
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from secure_protocol_v4.core import RoundSpec,Identity,Rejected,Ledger,decode,encode,verify
from secure_protocol_v4.node import Node
from secure_protocol_v4.transport import Group

def spec(kind='pairwise',n=3):
    roster=tuple(f'p{i:03}' for i in range(n))
    return RoundSpec('test-run','epoch1',roster[0],1,'matched-model','head-10x256+bias10',roster,2570,kind)
class ProtocolTests(unittest.TestCase):
    def test_strict_policy_and_safe_node_ids(self):
        for changes in [dict(round=True),dict(round=1.5),dict(length=True),dict(scale=False),dict(bound=True),
                        dict(bound=10**1000),dict(roster=['p000','p001','p002']),
                        dict(roster=('../p0','p001','p002')),dict(roster=('con','p001','p002')),
                        dict(roster=('p000','p000','p002')),dict(scale=2**1000)]:
            with self.subTest(changes=str(changes)[:100]),self.assertRaises(Rejected):dataclasses.replace(spec(),**changes)
    def test_tensor_schema_overflow_and_integer_policies(self):
        from secure_protocol_v4.model_adapter import flatten,restore,apply_aggregate,schema_id
        state={'weight':np.array([1.,2.],dtype=np.float32),'counter':np.array(1,dtype=np.int8),'buffer':np.array([1,2],dtype=np.int64)}
        v,s=flatten(state,['weight'])
        with self.assertRaises(Rejected):restore([1e300,1],s)
        for schema in [s+s,[dict(s[0],dtype='int64')],[dict(s[0],shape=[True,2])],[dict(s[0],size=3)],
                       [dict(s[0],name='')],[dict(s[0],shape=[2**63,2**63])]]:
            with self.subTest(schema=schema),self.assertRaises(Rejected):schema_id(schema)
        for maxima in [{'counter':1.5},{'counter':True},{'counter':128},{'counter':0},{'buffer':3}]:
            with self.subTest(maxima=maxima),self.assertRaises(Rejected):apply_aggregate(state,v,s,maxima)
        with self.assertRaises(Rejected):apply_aggregate(state,v,[dict(s[0],dtype='float16')])
        np.testing.assert_array_equal(state['weight'],[1.,2.]);self.assertEqual(state['counter'],1)
    def test_enrollment_is_validated_and_pinned_by_value(self):
        s=spec()
        with tempfile.TemporaryDirectory() as tmp:
            node=Node(s.target,s,Path(tmp)/'node.db')
            roster={n:Identity(n).registration() for n in s.roster};roster[s.target]=node.registration()
            bad=copy.deepcopy(roster);bad[s.roster[1]]['name']='other'
            with self.assertRaises(Rejected):node.pin(bad)
            bad=copy.deepcopy(roster);bad[s.roster[1]]['signing']=roster[s.target]['signing']
            with self.assertRaises(Rejected):node.pin(bad)
            bad=copy.deepcopy(roster);bad[s.roster[1]]['exchange']=encode(bytes(32))
            with self.assertRaises(Rejected):node.pin(bad)
            node.pin(roster);roster[s.roster[1]]['signing']='changed'
            self.assertNotEqual(node.roster[s.roster[1]]['signing'],'changed');node.ledger.db.close()
    def test_transport_framing_timeouts_and_error_redaction(self):
        s=spec();values={n:[.125]*s.length for n in s.roster}
        with Group(s,values) as group:
            tls=ssl.create_default_context(cafile=str(group.folder/'ca.pem'))
            tls.load_cert_chain(str(group.folder/(s.target+'.pem')),str(group.folder/(s.target+'.key')))
            def request(headers,body):
                with socket.create_connection(('localhost',group.addresses[s.target]),timeout=8) as raw:
                    with tls.wrap_socket(raw,server_hostname='localhost') as conn:
                        conn.sendall(b'POST /rpc HTTP/1.0\r\n'+headers+b'\r\n'+body)
                        result=b''
                        while True:
                            part=conn.recv(65536)
                            if not part:break
                            result+=part
                        self.assertIn(b'400 Bad Request',result)
                        self.assertIn(b'"error":"request rejected"',result)
            for body in [b'{"op":"contribute","op":"decrypt"}',b'{"op":"contribute","args":{"v":NaN}}',b'[]',b'{"op":"contribute","args":[]}']:
                request(b'Content-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\n',body)
            request(b'Content-Type: application/json\r\nContent-Length: 2\r\nContent-Length: 2\r\n',b'{}')
            request(b'Content-Type: application/json\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n',b'{}')
            start=time.monotonic()
            request(b'Content-Type: application/json\r\nContent-Length: 200\r\n',b'{')
            self.assertLess(time.monotonic()-start,7)
            with socket.create_connection(('localhost',group.addresses[s.target]),timeout=8) as stalled:
                stalled.sendall(b'\x16');start=time.monotonic()
                with self.assertRaises(Rejected):group.call(s.target,'decrypt')
                self.assertLess(time.monotonic()-start,7)
            saved=group.connections[s.target]
            wrong=http.client.HTTPSConnection('localhost',group.addresses[s.roster[1]],context=tls,timeout=8)
            group.connections[s.target]=wrong
            try:
                with self.assertRaisesRegex(Rejected,'wrong server identity'):group.call(s.target,'decrypt')
            finally:
                wrong.close();group.connections[s.target]=saved
            # Malformed requests and a stalled peer did not consume the real contribution.
            messages=group.contributions();candidate=group.average(messages)
            np.testing.assert_allclose(group.finish(messages,candidate),.125,atol=1/s.scale)
    def test_model_schema_and_ckks_fail_closed(self):
        from secure_protocol_v4.model_adapter import head,restore,apply_aggregate
        from secure_protocol_v4.openfhe_backend import CKKS
        state={'head.weight':np.zeros((10,256),dtype=np.float32),'head.bias':np.ones(10,dtype=np.float32),'counter':np.array(1,dtype=np.int64)}
        values,schema=head(state);self.assertEqual(len(values),2570)
        result=apply_aggregate(state,values+.01,schema,{'counter':4})
        self.assertEqual(result['head.weight'].dtype,np.float32);self.assertEqual(result['counter'],4)
        self.assertEqual(state['counter'],1)
        with self.assertRaises(Rejected):restore(values[:-1],schema)
        with self.assertRaises(Rejected):CKKS()
        with self.assertRaises(Rejected):dataclasses.replace(spec(),bound=float('nan'))
    def test_context_tamper_and_durable_replay(self):
        s=spec();i=Identity(s.target);roster={i.name:i.registration()};m=i.sign(s,'x',{'a':1})
        verify(m,s,'x',roster)
        with self.assertRaises(Rejected):verify(m,dataclasses.replace(s,round=2),'x',roster)
        m['body']['payload']['a']=2
        with self.assertRaises(Rejected):verify(m,s,'x',roster)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'state.db';a=Ledger(p);a.approve(s.slot,'a');a.db.close();b=Ledger(p)
            with self.assertRaises(Rejected):b.approve(s.slot,'b')
            b.consume(s.slot,'a')
            with self.assertRaises(Rejected):b.consume(s.slot,'a')
            b.db.close()
    def test_pairwise_mtls_processes_and_negative_requests(self):
        s=spec();g=np.random.default_rng(42);v={n:g.uniform(-.2,.2,2570).tolist() for n in s.roster}
        with Group(s,v) as group:
            self.assertEqual(len(set(group.pids.values())),3)
            messages=group.contributions();candidate=group.average(messages)
            tests=[dict(messages=messages[:-1],candidate=encode(candidate)),dict(messages=messages,candidate=messages[0]['body']['payload']['data'])]
            for args in tests:
                with self.assertRaises(Rejected):group.call(s.target,'approve',**args)
            modified=json.loads(json.dumps(messages));modified[1]['body']['context']='wrong-round'
            with self.assertRaises(Rejected):group.call(s.target,'approve',messages=modified,candidate=encode(candidate))
            with self.assertRaises(Rejected):group.call(s.target,'decrypt',data=messages[0]['body']['payload']['data'])
            actual=group.finish(messages,candidate);expected=np.mean(list(v.values()),axis=0)
            self.assertLess(float(np.max(np.abs(actual-expected))),1/s.scale)
            with self.assertRaises(Rejected):group.call(s.target,'approve',messages=messages,candidate=encode(candidate))
            with self.assertRaises(Rejected):group.call(s.target,'contribute')
    def test_bounds_and_missing_participant_fail_closed(self):
        s=spec()
        with tempfile.TemporaryDirectory() as tmp:
            nodes=[Node(n,s,Path(tmp)/(n+'.db')) for n in s.roster];roster={n.identity.name:n.registration() for n in nodes}
            for n in nodes:n.pin(roster)
            with self.assertRaises(Rejected):nodes[0].contribution([float('nan')]*s.length)
            with self.assertRaises(Rejected):nodes[0].contribution([s.bound+1]*s.length)
            msg=[n.contribution([.125]*s.length) for n in nodes]
            with self.assertRaises(Rejected):nodes[0].approve(msg[:-1],b'')
            other=dataclasses.replace(s,epoch='new')
            self.assertNotEqual(s.tag,other.tag)
            for node in nodes:node.ledger.db.close()
if __name__=='__main__':unittest.main()
