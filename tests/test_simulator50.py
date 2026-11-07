"""Trusted-simulator semantics, real CKKS, reproducibility and budget controls."""
import hashlib,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from simulator_pack.design import build,validate,prepare,configuration,atomic,digest,source_snapshot
from simulator_pack.engine import execute,completed

def fixture_cache(path,shape=(1,28,28),n=12):
    folder=Path(path)/'mnist';folder.mkdir(parents=True)
    rng=np.random.default_rng(42)
    for name,count in [('train',n),('validation',6),('test',6)]:np.savez(folder/(name+'.npz'),images=rng.integers(0,256,(count,*shape),dtype=np.uint8),labels=np.arange(count)%10)
    r=dict(dataset='mnist',input_shape=list(shape),normalization=dict(mean=[.5]*shape[0],std=[.25]*shape[0]),train=n,validation=6,test=6,
        sha256={name+'.npz':hashlib.sha256((folder/(name+'.npz')).read_bytes()).hexdigest() for name in ('train','validation','test')})
    r['receipt_sha256']=digest(r);atomic(folder/'receipt.json',r)

class SimulatorTests(unittest.TestCase):
    def test_design_balanced_models_modes_seeds_no_autostart(self):
        m=validate(build());self.assertEqual(m['candidate_jobs'],468);self.assertFalse(m['policy']['auto_start'])
        for b in m['bundles']:
            self.assertIn(len(b['jobs']),(6,30));self.assertEqual({j['config']['clients'] for j in b['jobs']},{50})
            self.assertEqual({j['config']['rounds'] for j in b['jobs']},{20})
        self.assertEqual({j['config']['dataset'] for b in m['bundles'] for j in b['jobs']},{'mnist','fashion_mnist','cifar10'})
    def test_matched_budget_and_shared_head_for_native_shapes(self):
        from matched_models import build_model
        torch.set_num_threads(1)
        for shape in [(1,28,28),(3,32,32)]:
            counts=[]
            for name in ('cnn','mlp'):
                model=build_model(name,shape);counts.append(sum(p.numel() for p in model.parameters()))
                self.assertEqual(model.head.weight.numel()+model.head.bias.numel(),2570);self.assertEqual(tuple(model(torch.zeros(2,*shape)).shape),(2,10))
            self.assertLess(abs(counts[0]-counts[1])/counts[0],.01)
    def test_all_five_modes_reconstruct_real_CKKS_and_preserve_integer_semantics(self):
        from simulator_pack.protection import mix,context
        from aggregation import average_state_dicts
        torch.set_num_threads(1);g=torch.Generator().manual_seed(44)
        states={i:{'head.weight':torch.randn(10,256,generator=g)*.02,'head.bias':torch.randn(10,generator=g)*.02,'features.weight':torch.randn(4,3,generator=g)*.02,'counter':torch.tensor(i)} for i in range(4)}
        before={i:{n:s[n]+.001*i for n in ['head.weight','head.bias']} for i,s in states.items()};graph={i:[(i-1)%4,(i+1)%4] for i in range(4)}
        cfg=configuration('cnn','cifar10','iid','none',1);contexts={i:context(cfg['CKKS']) for i in graph}
        for mode in ['none','masking','pairwise_masking','selective_he','adaptive_hybrid']:
            cfg['mode']=mode;result,stats=mix(states,before,graph,cfg,contexts,1)
            for i in graph:
                reference=average_state_dicts(states[j] for j in [i,*graph[i]])
                for n in reference:
                    if reference[n].is_floating_point():self.assertLess((result[i][n]-reference[n]).abs().max().item(),5e-5)
                    else:self.assertTrue(torch.equal(result[i][n],reference[n]))
            if mode in ('selective_he','adaptive_hybrid'):self.assertGreater(stats['he_ciphertext_bytes'],0)
            if mode=='adaptive_hybrid':self.assertEqual(len(stats['HE_targets']),2)
    def test_resume_equals_continuous_training_and_completed_is_noop(self):
        torch.set_num_threads(1)
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);fixture_cache(base/'data')
            cfg=configuration('mlp','mnist','iid','pairwise_masking',1,stage='calibration');cfg.update(clients=3,batch_size=2,test_fixture=True,validation_every=1)
            first=execute(base/'continuous',cfg,base/'data',device='cpu',keep_checkpoint=True)
            partial=execute(base/'resumed',cfg,base/'data',device='cpu',max_new_rounds=1,keep_checkpoint=True);self.assertEqual(partial['completed_rounds'],1)
            resumed=execute(base/'resumed',cfg,base/'data',device='cpu',keep_checkpoint=True)
            self.assertEqual(first['final_state_hash'],resumed['final_state_hash']);self.assertEqual(first['final_test'],resumed['final_test']);self.assertEqual(first['best_validation_test'],resumed['best_validation_test'])
            original=(base/'resumed/complete.json').read_bytes()
            with patch('client.Client.train_local',side_effect=AssertionError('completed training repeated')):
                self.assertTrue(execute(base/'resumed',cfg,base/'data',device='cpu')['no_op'])
            self.assertEqual(original,(base/'resumed/complete.json').read_bytes())
            (base/'resumed/metrics.json').write_text('[]')
            with patch('client.Client.train_local',side_effect=AssertionError('invalid completion repeated')):
                with self.assertRaisesRegex(RuntimeError,'archive invalid'):execute(base/'resumed',cfg,base/'data',device='cpu')
    def test_deadline_never_resets_on_resume(self):
        from simulator_pack.campaign import clock
        with tempfile.TemporaryDirectory() as tmp:
            prepare(tmp)
            with patch('simulator_pack.campaign.time.time',return_value=10000):first=clock(tmp)
            with patch('simulator_pack.campaign.time.time',return_value=1000000):second=clock(tmp)
            self.assertEqual(first,second);self.assertEqual(first,10000+120*3600)
    def test_expired_job_deadline_never_trains(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture_cache(root/'data')
            cfg=configuration('mlp','mnist','iid','none',1,stage='calibration');cfg.update(clients=3,test_fixture=True,batch_size=2)
            with patch('client.Client.train_local',side_effect=AssertionError('expired run trained')):
                result=execute(root/'job',cfg,root/'data',device='cpu',deadline=0)
            self.assertEqual(result['status'],'paused');self.assertEqual(result['completed_rounds'],0);self.assertFalse(completed(root/'job'))
    def test_budget_selection_keeps_whole_groups_and_excludes_uncalibrated_graphs(self):
        from simulator_pack.campaign import plan,clock
        with tempfile.TemporaryDirectory() as tmp:
            pack=Path(tmp);prepare(pack);clock(pack)
            for model in ['cnn','mlp']:
                for mode in ['none','masking','pairwise_masking','selective_he','adaptive_hybrid']:
                    cfg=configuration(model,'cifar10','iid',mode,0,stage='calibration');folder=pack/'calibration'/('cal-'+digest(cfg)[:24]);folder.mkdir(parents=True)
                    atomic(folder/'complete.json',dict(config=cfg,source_hash=source_snapshot()['hash'],runtime_sha256='fixture-profile',setup_seconds=1,test_final_seconds=1,test_best_seconds=1))
                    r=dict(timing_complete=True,training_seconds=1,aggregation_seconds=1,snapshot_seconds=.1,load_seconds=.1,checkpoint_seconds=.1,validation_seconds=1,validation=dict(accuracy=0))
                    atomic(folder/'metrics.json',[r,r])
            with patch('simulator_pack.engine.completed',return_value=True):selection=plan(pack)
            self.assertEqual(selection['status'],'ready');self.assertLessEqual(selection['estimated_seconds'],96*3600)
            self.assertTrue(any(e['reason']=='topology/mode calibration missing' for e in selection['excluded']))
            for b in selection['selected']:self.assertIn(len(b['job_ids']),(6,30))
            self.assertEqual(plan(pack),selection)
    def test_data_tamper_is_rejected(self):
        from simulator_pack.data import verify
        with tempfile.TemporaryDirectory() as tmp:
            fixture_cache(tmp);path=Path(tmp)/'mnist/train.npz';path.write_bytes(path.read_bytes()+b'changed')
            with self.assertRaisesRegex(RuntimeError,'cache changed'):verify(Path(tmp)/'mnist')

if __name__=='__main__':unittest.main()
