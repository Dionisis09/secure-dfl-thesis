"""Budget/control tests; synthetic timing fixtures are not performance evidence."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import laptop24 as lp
from simulator_pack.design import atomic, digest


def samples():
    receipt = dict(setup_seconds=1, test_final_seconds=1, test_best_seconds=1)
    record = dict(timing_complete=True, training_seconds=1, aggregation_seconds=1,
                  snapshot_seconds=.1, load_seconds=.1, checkpoint_seconds=.1,
                  validation_seconds=1, validation=dict(accuracy=0))
    return {lp.key(item['config']): (receipt, [record, record]) for item in lp.calibration_jobs()}


class LaptopTests(unittest.TestCase):
    def test_reduced_scope_preserves_recipe_seeds_and_modes(self):
        manifest = lp.build()
        jobs = [j for b in manifest['bundles'] for j in b['jobs']]
        self.assertEqual(len(jobs), 144)
        self.assertEqual(len({j['id'] for j in jobs}), 144)
        self.assertEqual(sum(len(b['jobs']) for b in manifest['bundles'] if b['required']), 60)
        for b in manifest['bundles']:
            self.assertEqual({j['config']['model'] for j in b['jobs']}, {'cnn', 'mlp'})
            for model in lp.MODELS:
                for mode in {j['config']['mode'] for j in b['jobs']}:
                    self.assertEqual({j['config']['seed'] for j in b['jobs'] if j['config']['model'] == model and j['config']['mode'] == mode}, {1, 2, 3})
        for j in jobs:
            cfg = j['config']
            self.assertEqual((cfg['rounds'], cfg['batch_size'], cfg['local_epochs']), (20, 128, 1))
            self.assertNotIn('sample_limit', cfg)
            self.assertIn(cfg['clients'], (20, 50))
        self.assertEqual({j['config']['seed'] for j in lp.calibration_jobs()}, {0})
        self.assertEqual(len(list(lp.calibration_jobs())), 22)

    def test_budget_removes_optional_whole_bundles_before_primary(self):
        manifest = lp.build()
        all_samples = samples()
        full = lp.admit(manifest, all_samples, 20*3600)
        primary = sum(b['estimated_seconds'] for b in full['selected'][:2])
        small = lp.admit(manifest, all_samples, primary + 1)
        self.assertEqual(small['status'], 'ready')
        self.assertEqual(sum(len(b['job_ids']) for b in small['selected']), 60)
        self.assertTrue(small['excluded'])
        blocked = lp.admit(manifest, all_samples, primary - 1)
        self.assertNotEqual(blocked['status'], 'ready')
        for b in full['selected']:
            self.assertIn(len(b['job_ids']), (12, 30))

    def test_missing_50_or_topology_calibration_never_extrapolates(self):
        available = {k: v for k, v in samples().items() if k[0] == 20 and k[3] == 'ring'}
        result = lp.admit(lp.build(), available, 20*3600)
        self.assertEqual(result['status'], 'ready')
        self.assertNotIn('scaling_50', {b['label'] for b in result['selected']})
        self.assertTrue(all(e['reason'] == 'calibration missing' for e in result['excluded']))

    def test_new_clock_starts_once_and_is_exactly24hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp)
            atomic(pack/'state.json', dict(started_UTC=None, deadline_UTC=None))
            with patch('laptop24.time.time', return_value=1000):
                deadline = lp.clock(pack)
            with patch('laptop24.time.time', return_value=999999):
                self.assertEqual(lp.clock(pack), deadline)
            self.assertEqual(deadline, 1000+24*3600)

    def test_plan_provenance_binds_source_hardware_clock_and_design(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp)
            atomic(pack/'hardware.json', {'fixture': True})
            atomic(pack/'state.json', dict(deadline_UTC='fixed'))
            plan = dict(manifest_sha256=lp.build()['sha256'], laptop_source_hash=lp.snapshot()['hash'],
                        hardware_sha256=digest({'fixture': True}), deadline_UTC='fixed')
            plan['sha256'] = digest(plan)
            lp.validate_selection(pack, plan)
            for field in ('manifest_sha256', 'laptop_source_hash', 'hardware_sha256', 'deadline_UTC'):
                bad = dict(plan)
                bad[field] = 'changed'
                bad['sha256'] = digest({k: v for k, v in bad.items() if k != 'sha256'})
                with self.assertRaisesRegex(RuntimeError, 'provenance'):
                    lp.validate_selection(pack, bad)

    def test_statistics_require_complete_three_seed_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp)
            bundle = lp.build()['bundles'][0]
            items = [j for j in bundle['jobs'] if j['config']['model'] == 'cnn' and j['config']['mode'] == 'none']
            manifest = dict(bundles=[dict(jobs=items)])
            for item in items:
                folder = pack/'results'/item['id']
                cfg = item['config']
                atomic(folder/'complete.json', dict(config=cfg, final_test=dict(accuracy=80+cfg['seed'], loss=1.), recorded_job_seconds=100.))
                atomic(folder/'metrics.json', [dict(round=k, validation=dict(accuracy=k)) for k in range(1, 21)])
            atomic(pack/'hardware.json', {'fixture': True})
            with patch('laptop24.checked', return_value=manifest), patch('laptop24.status', return_value={}), patch('laptop24.valid_result', return_value=True):
                result = lp.summarize(pack)
            row = result['groups'][0]
            self.assertEqual(row['statistics']['accuracy'], dict(mean=82, sample_SD=1.))
            with patch('laptop24.checked', return_value=manifest), patch('laptop24.status', return_value={}), patch('laptop24.valid_result', side_effect=lambda p, i, cfg: cfg['seed'] != 3):
                result = lp.summarize(pack)
            self.assertIsNone(result['groups'][0]['statistics'])
            self.assertFalse(result['groups'][0]['complete_three_seeds'])

    def test_existing_server_source_snapshot_remains_valid(self):
        frozen = lp.load(lp.ROOT/'simulator4090_scaling_pack_20261107/source_snapshot.json')
        self.assertEqual(frozen, lp.engine_source())


if __name__ == '__main__':
    unittest.main()
