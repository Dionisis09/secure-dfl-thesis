import copy,json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from experiment_pack.manifest import build,validate,config,digest

class PackDesignTests(unittest.TestCase):
    def test_rpc_audit_memory_is_bounded_for_long_campaigns(self):
        import ssl,threading
        from unittest.mock import MagicMock
        from independent_clients.network import RemoteClients
        remote=RemoteClients.__new__(RemoteClients);connection=MagicMock();connection.sock=MagicMock(spec=ssl.SSLSocket)
        connection.sock.getpeercert.return_value={'subject':((('commonName','p000'),),)}
        response=MagicMock();response.status=200;response.read.return_value=b'{"ok":true,"result":{}}';connection.getresponse.return_value=response
        remote.connections={'p000':connection};remote.calls=[];remote.audit_mode='aggregate';remote.audit_totals={};remote.request_bytes=remote.response_bytes=0;remote.lock=threading.Lock()
        for _ in range(2000):remote.call('p000','status')
        self.assertEqual(len(remote.calls),100);self.assertEqual(len(remote.audit_totals),1)
        self.assertEqual(next(iter(remote.audit_totals.values()))['calls'],2000)
    def test_build_is_nonexecuting_and_preserves_existing_state(self):
        from experiment_pack.controller import build_pack,dump
        with tempfile.TemporaryDirectory() as directory:
            m=build_pack(directory);loaded=json.loads((Path(directory)/'manifest.json').read_text());self.assertEqual(validate(loaded),m['counts'])
            state=dict(status='paused',completed=['kept'],failed=[],current=None,GPU_validated=False)
            dump(Path(directory)/'state.json',state);build_pack(directory)
            self.assertEqual(json.loads((Path(directory)/'state.json').read_text()),state)
    def test_network_dirichlet_50_clients_has_feasible_minimum(self):
        import numpy as np
        from data_utils import create_client_loaders
        from experiment_pack.provision import Labels
        cfg=config('mlp','cifar10','dirichlet',.1,'ring','pairwise_masking',1,'network',lr=.001)
        self.assertEqual(cfg['dirichlet_min_samples'],2)
        dataset=Labels(np.tile(np.arange(10),150))
        for seed in (1,2,3):
            loaders=create_client_loaders(dataset,50,128,'dirichlet',seed,.1,cfg['dirichlet_min_samples'])
            self.assertGreaterEqual(min(len(l.dataset) for l in loaders),2)
            self.assertEqual(sum(len(l.dataset) for l in loaders),1500)
    def test_all_dataset_model_inputs_share_2570_head(self):
        import torch
        from matched_models import build_model
        torch.set_num_threads(1)
        for shape in [(1,28,28),(3,32,32)]:
            counts=[]
            for name in ('mlp','cnn'):
                model=build_model(name,shape);self.assertEqual(tuple(model(torch.zeros(2,*shape)).shape),(2,10))
                self.assertEqual(model.head.weight.numel()+model.head.bias.numel(),2570);counts.append(sum(p.numel() for p in model.parameters()))
            self.assertLess(abs(counts[0]-counts[1])/counts[1],.01)
    @unittest.skipUnless(sys.platform=='linux','Linux role isolation required')
    def test_client_can_replace_python_but_not_execute_shell(self):
        import subprocess
        source=str(Path(__file__).resolve().parents[1]/'src')
        program='''import os,sys
sys.path.insert(0,sys.argv[1])
from independent_clients.isolation import restrict_files
restrict_files(sys.argv[2],allow_python_exec=True)
try:os.execve('/bin/sh',['sh','-c','exit 19'],os.environ)
except PermissionError:pass
else:raise RuntimeError('shell execution allowed')
os.execve(sys.executable,[sys.executable,'-c','print("private_python_worker_ok")'],os.environ)
'''
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,'-c',program,source,directory],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn('private_python_worker_ok',result.stdout)
    def test_complete_grid_50clients_three_seeds_unique_dependencies(self):
        m=build();counts=validate(m)
        self.assertEqual(counts,dict(gpu_gate=2,smoke=12,tuning=36,validation=2160,sensitivity=360,network=540))
        self.assertEqual(m['unique_jobs'],3110);self.assertEqual(len(m['sensitivity_references']),90)
        self.assertEqual({j['config']['clients'] for j in m['jobs']},{50})
        changed=copy.deepcopy(m);changed['jobs'][50]['config']['seed']=99
        with self.assertRaises(ValueError):validate(changed)
    def test_real_topologies_and_single_target_assignment(self):
        from experiment_pack.groups import groups
        signatures=[]
        for topology in ('ring','fully_connected','caveman','barabasi_albert'):
            cfg=config('cnn','cifar10','iid',None,topology,'adaptive_hybrid',1)
            gs,graph,selected=groups(cfg)
            self.assertEqual(len(selected),20)
            self.assertEqual(sorted(t for g in gs for t in g['targets']),sorted(graph))
            self.assertTrue(all(set(g['roster'])=={target,*graph[target]} for g in gs for target in g['targets']))
            signatures.append(json.dumps(graph,sort_keys=True))
        self.assertEqual(len(set(signatures)),4)
        for seed in (0,1,2,3,7):
            cfg=config('cnn','cifar10','iid',None,'barabasi_albert','hybrid_pairwise_head_he',seed)
            gs,graph,_=groups(cfg)
            self.assertGreaterEqual(min(map(len,graph.values())),2)
            self.assertTrue(all(len(g['roster'])>=3 for g in gs))
    def test_no_test_selection_in_tuning(self):
        self.assertEqual({j['config']['test_policy'] for j in build()['jobs'] if j['config']['workflow']=='tuning'},{'never'})
    def test_folds_disjoint_stratified_and_repeatable(self):
        import numpy as np
        from experiment_pack.data import stratified
        labels=np.tile(np.arange(10),100)
        t,v=stratified(labels);self.assertFalse(set(t)&set(v));self.assertEqual(len(t),900);self.assertEqual(len(v),100)
        np.testing.assert_array_equal(stratified(labels)[0],t)
    def test_outer_envelope_tamper_replay_wrong_recipient(self):
        from secure_protocol_v4.core import Identity,Rejected
        from experiment_pack.envelope import seal,open_envelope
        peers={n:Identity(n) for n in ['p000','p001','p002']};roster={n:i.registration() for n,i in peers.items()};context='a'*64
        payload=dict(private_values=[1,2,3]);envelope=seal(peers['p000'],'p001',roster,context,'chunk:0',payload)
        self.assertEqual(open_envelope(peers['p001'],'p000',roster,context,'chunk:0',envelope),payload)
        for recipient,ctx,label in [('p002',context,'chunk:0'),('p001','b'*64,'chunk:0'),('p001',context,'chunk:1')]:
            with self.assertRaises(Rejected):open_envelope(peers[recipient],'p000',roster,ctx,label,envelope)
        envelope['body']['ciphertext']='AAAA'
        with self.assertRaises(Rejected):open_envelope(peers['p001'],'p000',roster,context,'chunk:0',envelope)

class ClientSessionTests(unittest.TestCase):
    def run_mode(self,mode):
        import numpy as np,torch
        from secure_protocol_v4.core import Identity,Rejected
        from experiment_pack.session import Session,phases
        from secure_protocol_v6.training_adapter import state_hash
        if mode in ('selective_he','hybrid_pairwise_head_he'):
            from secure_protocol_v6.rangeproof import info
            try:info()
            except Rejected:
                if os.environ.get('DFL_REQUIRE_NATIVE')=='1':raise
                self.skipTest('native Bulletproof backend required')
        peers={n:Identity(n) for n in ['p000','p001','p002']};rr={n:i.registration() for n,i in peers.items()}
        group=dict(id='test_group',roster=list(peers),targets=list(peers),mode=mode)
        rng=np.random.default_rng(9)
        states={n:{'features.weight':torch.tensor(rng.normal(0,.02,(4,8)),dtype=torch.float32),
            'head.weight':torch.tensor(rng.normal(0,.02,(10,256)),dtype=torch.float32),'head.bias':torch.tensor(rng.normal(0,.02,10),dtype=torch.float32)} for n in peers}
        expected={k:torch.tensor(sum(np.rint(s[k].numpy()*65536).astype(np.int64) for s in states.values())/(3*65536),dtype=v.dtype) for k,v in states['p000'].items()}
        with tempfile.TemporaryDirectory() as tmp:
            sessions={n:Session(n,i,rr,group,states[n],run='test',epoch='f'*32,number=1,model='tiny',schema='test-schema',folder=Path(tmp)/n) for n,i in peers.items()}
            try:
                sample=sessions['p000']
                for phase,index,route in phases(sample.spec.length,sample.split):
                    for session in sessions.values():session.act(phase,index)
                    if route:
                        for sender,session in sessions.items():
                            for recipient,receiver in sessions.items():receiver.ingest(phase,index,sender,session.emit(phase,index,recipient))
                self.assertEqual({state_hash(s.result) for s in sessions.values()},{state_hash(expected)})
                with self.assertRaises(Rejected):sample.act('blob_commit')
            finally:
                for session in sessions.values():session.close()
    def test_plain_baseline(self):self.run_mode('none')
    def test_legacy_public_mask_ablation(self):self.run_mode('masking')
    def test_pairwise_full_model(self):self.run_mode('pairwise_masking')
    def test_selective_HE(self):self.run_mode('selective_he')
    def test_hybrid_HE(self):self.run_mode('hybrid_pairwise_head_he')

if __name__=='__main__':unittest.main()
