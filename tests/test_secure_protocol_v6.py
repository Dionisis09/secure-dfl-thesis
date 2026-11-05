import dataclasses,hashlib,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from secure_protocol_v4.core import Rejected,encode,decode,digest,RoundSpec as BlobSpec
from secure_protocol_v4 import pairwise
from secure_protocol_v6.node import Node,RoundSpec
from secure_protocol_v6 import crypto as c,rangeproof as rp
from secure_protocol_v6.chunked import ChunkNode,CHUNK_VALUES,aggregate_group

def policy(length=4):return RoundSpec('v6-unit','epoch','p000',1,'model','schema',('p000','p001','p002'),length)
def require_native(test):
    try:return rp.info()
    except Rejected:
        if os.environ.get('DFL_REQUIRE_NATIVE')=='1':raise
        test.skipTest('native Bulletproofs build required (server gate requires it)')

class RangeTests(unittest.TestCase):
    def setUp(self):
        require_native(self);self.tmp=tempfile.TemporaryDirectory();self.spec=policy()
        self.nodes=[Node(n,self.spec,Path(self.tmp.name)/(n+'.db')) for n in self.spec.roster]
        roster={n.identity.name:n.registration() for n in self.nodes}
        for node in self.nodes:node.pin(roster)
        keys=[n.keygen() for n in self.nodes]
        for node in self.nodes:node.set_keys(keys)
    def tearDown(self):
        for node in self.nodes:node.ledger.db.close()
        self.tmp.cleanup()
    def test_both_signed_endpoints_and_exact_recovery(self):
        values=[self.spec.bound,-self.spec.bound,0,.5/self.spec.scale]
        messages=[n.contribution(values) for n in self.nodes]
        candidate=self.nodes[0].recompute(messages)
        approvals=[n.approve(messages,candidate) for n in self.nodes]
        releases=[n.release(messages,candidate,approvals) for n in self.nodes]
        from secure_protocol_v4.core import aggregate_tag
        tag=aggregate_tag(self.spec,messages,encode(candidate));columns=[]
        for node,message in zip(self.nodes,releases):columns.append(c.verify_partial(decode(message['body']['payload']['data']),candidate,self.spec,node.keys[node.identity.name],tag,node.identity.name))
        decoder=c.BoundedLog(3*self.spec.scale+3)
        actual=[]
        for i,(_,C) in c.chunks(candidate,64,self.spec.length):
            total=c.IDENTITY
            for column in columns:total=c.add(total,column[i])
            actual.append(decoder.decode(c.sub(C,total))/(3*self.spec.scale))
        np.testing.assert_array_equal(actual,np.rint(np.asarray(values)*self.spec.scale)/self.spec.scale)
    def test_valid_signed_outside_range_knowledge_proofs_rejected(self):
        messages=[n.contribution([0.]*self.spec.length) for n in self.nodes];attacker=self.nodes[0]
        for integer in [rp.bound_integer(self.spec)+1,-rp.bound_integer(self.spec)-1]:
            data,blindings=c._encrypt_records([integer]*self.spec.length,self.spec,attacker.public,attacker.key_id,'p000')
            context=c.range_context(data,self.spec,attacker.key_id,'p000')
            # Matching context and blindings, but a proof for another plaintext.
            wrong_proof=rp.prove([0]*self.spec.length,blindings,self.spec,context)
            forged=attacker.identity.sign(self.spec,'contribution',{'data':encode(data),'range_proof':encode(wrong_proof)})
            with self.assertRaisesRegex(Rejected,'range proof'):self.nodes[1].recompute([forged]+messages[1:])
            with self.assertRaises(Rejected):rp.prove([integer]*self.spec.length,blindings,self.spec,context)
    def test_missing_tampered_and_cross_context_proofs(self):
        messages=[n.contribution([.1]*self.spec.length) for n in self.nodes];a=self.nodes[0]
        payload=messages[0]['body']['payload'];proof=decode(payload['range_proof'])
        cases=[{'data':payload['data']},{**payload,'range_proof':encode(proof[:-1])},{**payload,'range_proof':encode(proof+b'junk')}]
        for bad in cases:
            forged=a.identity.sign(self.spec,'contribution',bad)
            with self.assertRaises(Rejected):self.nodes[1].recompute([forged]+messages[1:])
        data=decode(payload['data']);commitments=[record[2] for _,record in c.chunks(data,288,self.spec.length)]
        with self.assertRaises(Rejected):rp.verify(commitments,proof,self.spec,b'\x01'*32)
    def test_range_commitment_is_linked_to_ciphertext(self):
        a=self.nodes[0];data,proof=c.encrypt([.1]*self.spec.length,self.spec,a.public,a.key_id,'p000')
        # V substituted independently: a valid range proof cannot bypass the AND link.
        altered=data[:64]+c.add(data[64:96],c.base(c.scalar(1)))+data[96:]
        with self.assertRaisesRegex(Rejected,'knowledge proof'):c.verify_cipher(altered,proof,self.spec,a.public,a.key_id,'p000')

class ChunkTests(unittest.TestCase):
    def test_streamed_full_vector_and_commitment_abort(self):
        length=CHUNK_VALUES+3;roster=('p000','p001','p002')
        spec=BlobSpec('blob-test','epoch','p000',1,'model','schema',roster,length,'pairwise',65536,32.)
        with tempfile.TemporaryDirectory() as tmp:
            nodes=[ChunkNode(n,spec,Path(tmp)/(n+'.db')) for n in roster];registry={n.identity.name:n.registration() for n in nodes}
            for node in nodes:node.pin(registry)
            values=[np.full(length,(i+1)*.125) for i in range(3)]
            commits=[node.rpc('prepare',{},value) for node,value in zip(nodes,values)]
            for node in nodes:node.rpc('begin',{'commitments':commits},None)
            with self.assertRaises(Rejected):nodes[0].rpc('accept_chunk',{'index':1,'messages':[]},None)
            for index in range(2):
                messages=[node.rpc('chunk',{'index':index},None) for node in nodes]
                for node in nodes:node.rpc('accept_chunk',{'index':index,'messages':messages},None)
            for node in nodes:np.testing.assert_array_equal(pairwise.recover(pairwise.pack(node.total),spec),np.mean(values,axis=0))
            approvals=[node.rpc('approve_blob',{'digest':digest(pairwise.pack(node.total))},None) for node in nodes]
            for node in nodes:node.rpc('release_blob',{'approvals':approvals},None)
            with self.assertRaises(Rejected):nodes[0].rpc('release_blob',{'approvals':approvals},None)
            for node in nodes:node.ledger.db.close()
        # Fresh recipient sees a validly signed false whole-vector commitment.
        with tempfile.TemporaryDirectory() as tmp:
            nodes=[ChunkNode(n,spec,Path(tmp)/(n+'.db')) for n in roster];registry={n.identity.name:n.registration() for n in nodes}
            for node in nodes:node.pin(registry)
            commits=[node.rpc('prepare',{},value) for node,value in zip(nodes,values)]
            commits[0]=nodes[0].identity.sign(spec,'blob_commit',dict(hash='0'*64,bytes=8*length,chunk_values=CHUNK_VALUES))
            nodes[1].rpc('begin',{'commitments':commits},None)
            for index in range(2):
                messages=[node.rpc('chunk',{'index':index},None) for node in nodes]
                if index==0:nodes[1].rpc('accept_chunk',{'index':index,'messages':messages},None)
                else:
                    with self.assertRaises(Rejected):nodes[1].rpc('accept_chunk',{'index':index,'messages':messages},None)
            with self.assertRaisesRegex(Rejected,'aborted'):nodes[1].rpc('approve_blob',{'digest':digest(pairwise.pack(nodes[1].total))},None)
            for node in nodes:node.ledger.db.close()
    def test_network_chunk_stream(self):
        from secure_protocol_v6.transport import Group
        roster=('p000','p001','p002');spec=BlobSpec('blob-net','epoch','p000',1,'m','s',roster,CHUNK_VALUES+1,'pairwise',65536,32.)
        with Group(spec,{n:np.full(spec.length,.125) for n in roster}) as group:
            result,_=aggregate_group(group);np.testing.assert_array_equal(result,.125)

class BackendTests(unittest.TestCase):
    def test_missing_backend_fails_closed(self):
        rp.backend.cache_clear();rp.info.cache_clear()
        try:
            with patch.dict(os.environ,{'DFL_RANGE_LIB':str(Path(tempfile.gettempdir())/'definitely-missing-dfl-range-lib')}):
                with self.assertRaisesRegex(Rejected,'No unproved fallback'):rp.info()
        finally:rp.backend.cache_clear();rp.info.cache_clear()
if __name__=='__main__':unittest.main()
