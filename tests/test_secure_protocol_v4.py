import dataclasses,json,sys,tempfile,unittest
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
