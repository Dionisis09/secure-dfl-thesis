"""Eight-hour budget, real-reference cost projection and complete seed cohorts."""
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import overnight8 as n
from simulator_pack.design import atomic


class OvernightTests(unittest.TestCase):
    def test_prespecified_design_and_schedule(self):
        m=n.build()
        jobs=[j for b in m['bundles'] for j in b['jobs']]
        self.assertEqual(len(jobs),36)
        self.assertEqual(len({j['id'] for j in jobs}),36)
        self.assertEqual(sum(len(b['jobs']) for b in m['bundles'] if b['required']),24)
        for b in m['bundles']:
            for model in n.lp.MODELS:
                for mode in n.lp.PAIR:
                    self.assertEqual({j['config']['seed'] for j in b['jobs'] if j['config']['model']==model and j['config']['mode']==mode},{1,2,3})
        for j in jobs:
            c=j['config']
            self.assertEqual((c['clients'],c['rounds'],c['schedule_rounds'],c['batch_size']),(20,60,60,128))
            self.assertNotIn('sample_limit',c)
            factor=lambda r:.5*(1+math.cos(math.pi*(r-3)/(c['schedule_rounds']-3)))
            self.assertGreater(factor(21),0)
            self.assertEqual(factor(60),0)
        self.assertEqual({j['config']['seed'] for j in n.calibrations()},{0})

    def test_optional_stress_is_dropped_before_required_convergence(self):
        m=n.build()
        estimates={n.key(j['config']):100 for b in m['bundles'] for j in b['jobs']}
        ready=n.admit(m,estimates,2401)
        self.assertEqual(ready['status'],'ready')
        self.assertEqual(sum(len(b['job_ids']) for b in ready['selected']),24)
        self.assertEqual(len(ready['excluded']),1)
        self.assertEqual(n.admit(m,estimates,2399)['status'],'admission_blocked')

    def test_no_alpha0_1_admission_from_alpha0_5_alone(self):
        m=n.build()
        estimates={n.key(j['config']):100 for b in m['bundles'] if b['required'] for j in b['jobs']}
        selection=n.admit(m,estimates,7*3600)
        self.assertEqual(sum(len(b['job_ids']) for b in selection['selected']),24)
        self.assertEqual(selection['excluded'][0]['reason'],'calibration missing')

    def test_eight_hour_clock_never_restarts_or_extends(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            atomic(p/'state.json',dict(started_UTC=None,deadline_UTC=None))
            with patch('overnight8.time.time',return_value=1000):first=n.clock(p)
            with patch('overnight8.time.time',return_value=999999):self.assertEqual(n.clock(p),first)
            self.assertEqual(first,1000+8*3600)
            state=n.lp.load(p/'state.json')
            state['deadline_UTC']=n.utc(1000+9*3600)
            atomic(p/'state.json',state)
            with self.assertRaisesRegex(RuntimeError,'invalid8hour'):n.clock(p)

    def test_projection_accounts_for60rounds12validations_two_tests_and_margin(self):
        r=dict(setup_seconds=1,test_final_seconds=3,test_best_seconds=4)
        record=dict(timing_complete=True,training_seconds=1,aggregation_seconds=2,snapshot_seconds=3,
                    load_seconds=4,checkpoint_seconds=5,validation_seconds=6,validation=dict(accuracy=0))
        self.assertEqual(n.predicted(r,[record,record]),2*(1+60*15+12*6+3+4+5))
        record['timing_complete']=False
        with self.assertRaisesRegex(RuntimeError,'incomplete'):n.predicted(r,[record])

    def test_windows_stop_includes_own_child_subtree(self):
        process=Mock(pid=12345)
        process.poll.return_value=None
        with patch('overnight8.os.name','nt'), patch('overnight8.subprocess.run') as run:
            n.stop_child(process)
        self.assertEqual(run.call_args.args[0],['taskkill','/PID','12345','/T','/F'])
        process.wait.assert_called_once()

    def test_existing_laptop_and_server_frozen_sources_are_preserved(self):
        self.assertEqual(n.lp.snapshot(),n.lp.load(n.REFERENCE/'source_snapshot.json'))
        self.assertEqual(n.lp.engine_source(),n.lp.load(n.ROOT/'simulator4090_scaling_pack_20261107/source_snapshot.json'))


if __name__=='__main__':unittest.main()
