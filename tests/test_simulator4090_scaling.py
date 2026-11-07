"""Scaling admission, provenance, reporting and real100-client head reconstruction.

Synthetic timings are admission fixtures, never hardware performance evidence.
"""
import itertools,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from simulator_pack.design import build,validate,prepare,configuration,atomic,digest,source_snapshot
from simulator_pack.campaign import require_target,calibration_configs,plan,clock,utc

PROFILE=dict(device='cuda',GPU='NVIDIA GeForce RTX 4090',GPU_memory_bytes=24*1024**3,fixture=True)

def fixture_pack(path):
    path=Path(path);old=path/'old.json';atomic(old,dict(started_UTC=utc(time.time()-60),deadline_UTC=utc(time.time()+120*3600-60)))
    pack=path/'pack';prepare(pack,scaling4090=True,clock_from=old)
    data=dict(cifar10=dict(receipt_sha256='synthetic-data'))
    atomic(pack/'data_snapshot.json',dict(datasets=data,sha256=digest(data)));return pack

def fixture_calibrations(pack,missing100=False,seconds=1,profile=None):
    profile=profile or PROFILE
    m=json.loads((pack/'manifest.json').read_text())
    for cfg in calibration_configs(m,('ring',)):
        if missing100 and cfg['clients']==100:continue
        folder=pack/'calibration'/('cal-'+digest(cfg)[:24]);folder.mkdir(parents=True,exist_ok=True)
        atomic(folder/'complete.json',dict(config=cfg,source_hash=source_snapshot()['hash'],runtime_sha256=digest(profile),runtime_profile=profile,
            data_receipt_sha256='synthetic-data',setup_seconds=1,test_final_seconds=1,test_best_seconds=1))
        r=dict(timing_complete=True,training_seconds=seconds,aggregation_seconds=seconds,snapshot_seconds=.1,load_seconds=.1,checkpoint_seconds=.1,validation_seconds=1,validation=dict(accuracy=0))
        atomic(folder/'metrics.json',[r,r])

class ScalingTests(unittest.TestCase):
    def test_shared_50_references_and_balanced_new24(self):
        old=validate(build());m=validate(build(True));s=m['scaling'];oldids={j['id'] for b in old['bundles'] for j in b['jobs']}
        self.assertEqual(m['candidate_jobs'],492);self.assertEqual(len(s['new_job_ids']),24);self.assertEqual(len(s['reference_50_job_ids']),12)
        self.assertTrue(set(s['reference_50_job_ids'])<=oldids);self.assertFalse(set(s['new_job_ids'])&oldids)
        required={j['id'] for b in m['bundles'] if b['id'] in m['policy']['required_bundle_ids'] for j in b['jobs']}
        self.assertEqual(len(required),114);self.assertTrue(set(s['new_job_ids']+s['reference_50_job_ids'])<=required)
        cases=list(calibration_configs(m,('ring','caveman','barabasi_albert')))
        self.assertEqual(len(cases),38);self.assertEqual(len({digest(c) for c in cases}),38)
        self.assertEqual({c['split'] for c in cases},{'dirichlet'})

    def test_inherited_clock_survives_migration_and_rejects_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack=fixture_pack(tmp);state=json.loads((pack/'state.json').read_text());deadline=clock(pack)
            self.assertEqual(deadline,__import__('datetime').datetime.fromisoformat(state['deadline_UTC']).timestamp())
            with patch('simulator_pack.campaign.time.time',return_value=time.time()+999999):self.assertEqual(clock(pack),deadline)
            state['started_UTC']=None;atomic(pack/'state.json',state)
            with self.assertRaisesRegex(RuntimeError,'missing inherited clock'):clock(pack)

    def test_laptop_cpu_and_low_vram_cannot_admit_target(self):
        m=build(True);require_target(m,PROFILE)
        for bad in [dict(PROFILE,GPU='NVIDIA GeForce RTX 5070'),dict(PROFILE,device='cpu'),dict(PROFILE,GPU_memory_bytes=8*1024**3)]:
            with self.assertRaisesRegex(RuntimeError,'requires RTX4090'):require_target(m,bad)

    def test_no_extrapolation_to100_and_replan_after_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack=fixture_pack(tmp);fixture_calibrations(pack,missing100=True)
            with patch('simulator_pack.engine.completed',return_value=True):blocked=plan(pack)
            self.assertNotEqual(blocked['status'],'ready');self.assertFalse((pack/'selected_plan.json').exists())
            fixture_calibrations(pack)
            with patch('simulator_pack.engine.completed',return_value=True):ready=plan(pack)
            self.assertEqual(ready['status'],'ready');ids={i for b in ready['selected'] for i in b['job_ids']}
            m=build(True);self.assertTrue(set(m['scaling']['new_job_ids']+m['scaling']['reference_50_job_ids'])<=ids)
            self.assertLessEqual(ready['estimated_seconds'],96*3600)

    def test_budget_refuses_partial_scaling_and_rejects_laptop_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack=fixture_pack(tmp);fixture_calibrations(pack,seconds=10000)
            with patch('simulator_pack.engine.completed',return_value=True):blocked=plan(pack)
            self.assertNotEqual(blocked['status'],'ready');self.assertFalse((pack/'selected_plan.json').exists())
            fixture_calibrations(pack,profile=dict(PROFILE,GPU='RTX 5070'))
            with patch('simulator_pack.engine.completed',return_value=True):
                with self.assertRaisesRegex(RuntimeError,'requires RTX4090'):plan(pack)

    def test_official_fold_partition_coverage_and_minimum_for20_50_100(self):
        from data_utils import create_client_loaders
        class Labels(torch.utils.data.Dataset):
            targets=torch.arange(45000)%10
            def __len__(self):return len(self.targets)
            def __getitem__(self,i):return torch.zeros(1),int(self.targets[i])
        for n,seed in itertools.product((20,50,100),(1,2,3)):
            loaders=create_client_loaders(Labels(),n,128,'dirichlet',seed,.5,10,2)
            groups=[l.dataset.indices for l in loaders]
            self.assertEqual(sorted(i for group in groups for i in group),list(range(45000)))
            self.assertGreaterEqual(min(map(len,groups)),10)

    def test_real_CKKS100_logical_clients_with2570_value_head(self):
        from simulator_pack.protection import mix,context
        from aggregation import average_state_dicts
        torch.set_num_threads(1);g=torch.Generator().manual_seed(123)
        states={i:{'head.weight':torch.randn(10,256,generator=g)*.02,'head.bias':torch.randn(10,generator=g)*.02,
            'features.weight':torch.randn(2,3,generator=g)*.02,'counter':torch.tensor(i)} for i in range(100)}
        before={i:{k:s[k]+.001*i for k in ('head.weight','head.bias')} for i,s in states.items()}
        graph={i:[(i-1)%100,(i+1)%100] for i in states};cfg=configuration('cnn','cifar10','dirichlet','adaptive_hybrid',1,alpha=.5,clients=100)
        # One real context shared ONLY by this arithmetic fixture; production allocates per-target contexts.
        ckks=context(cfg['CKKS']);result,stats=mix(states,before,graph,cfg,{i:ckks for i in graph},1)
        self.assertEqual(len(stats['HE_targets']),40);self.assertGreater(stats['he_ciphertext_bytes'],0)
        for i in graph:
            reference=average_state_dicts(states[j] for j in [i,*graph[i]])
            for key in reference:
                if reference[key].is_floating_point():self.assertLess((result[i][key]-reference[key]).abs().max().item(),5e-5)
                else:self.assertTrue(torch.equal(result[i][key],reference[key]))

    def test_report_keeps_client_counts_separate_and_requires_all_three_seeds(self):
        from simulator_pack.report import summarize
        with tempfile.TemporaryDirectory() as tmp:
            pack=fixture_pack(tmp);m=build(True);lookup={j['id']:j for b in m['bundles'] for j in b['jobs']};ids=m['scaling']['new_job_ids']+m['scaling']['reference_50_job_ids']
            existing=set()
            for i in ids:
                cfg=lookup[i]['config'];folder=pack/'results'/i;folder.mkdir(parents=True)
                atomic(folder/'complete.json',dict(config=cfg,runtime_profile=PROFILE,runtime_sha256=digest(PROFILE),source_hash=source_snapshot()['hash'],data_receipt_sha256='synthetic-data',
                    final_test=dict(accuracy=cfg['clients']+cfg['seed'],loss=1.),best_validation_test=dict(accuracy=42.),recorded_job_seconds=float(cfg['clients'])))
                atomic(folder/'metrics.json',[dict(round=k,validation=dict(accuracy=k)) for k in range(1,21)])
                existing.add(str(folder))
            with patch('simulator_pack.report.completed',side_effect=lambda folder,*args:str(folder) in existing):r=summarize(pack)
            self.assertTrue(r['scaling']['complete_scaling']);self.assertEqual(len(r['groups']),12)
            for row in r['scaling']['groups']:
                self.assertEqual(row['statistics']['accuracy']['mean'],row['clients']+2)
                self.assertEqual(row['statistics']['accuracy']['sample_SD'],1)
            existing.remove(str(pack/'results'/ids[0]))
            with patch('simulator_pack.report.completed',side_effect=lambda folder,*args:str(folder) in existing):r=summarize(pack)
            self.assertFalse(r['scaling']['complete_scaling']);self.assertEqual(r['scaling']['completed_cases'],35)
            self.assertEqual(sum(row['statistics'] is None for row in r['scaling']['groups']),1)

if __name__=='__main__':unittest.main()
