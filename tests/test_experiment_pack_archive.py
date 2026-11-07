"""Controller/archive regression fixtures; no training, services or GPU required."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from experiment_pack.controller import build_pack,dump,execute,verify_completed
from experiment_pack.manifest import digest
from experiment_pack.launch import export_and_prune

@unittest.skipUnless(sys.platform=='linux','Linux supervisor required')
class ArchiveRegressionTests(unittest.TestCase):
    def prepare(self,base,identifier,model='mlp'):
        root=base/'work'/identifier;root.mkdir(parents=True)
        cfg=dict(rounds=2,model=model,declared_config_sha256=digest(identifier))
        job=dict(job_id=digest(cfg),config=cfg,source_hash='fixture')
        (root/'.experiment-pack-owned').write_text(job['job_id'])
        dump(root/'public_job.json',job)
        records=[dict(round=n,seconds=float(n)) for n in (1,2)]
        dump(root/'coordinator/journal.json',dict(job_id=job['job_id'],completed=2,records=records,pending=None))
        receipt=dict(status='completed',job_id=job['job_id'],completed_rounds=2,records=records)
        return root,job,receipt

    def test_reexport_is_idempotent_checksums_never_include_themselves(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root,job,receipt=self.prepare(base,'first')
            dest=base/'results/first'
            export_and_prune(root,dest,base/'work',receipt,prune=False)
            first=(dest/'checksums.json').read_bytes()
            export_and_prune(root,dest,base/'work',receipt,prune=False)
            self.assertEqual(first,(dest/'checksums.json').read_bytes())
            self.assertNotIn('checksums.json',json.loads(first))
            self.assertTrue(verify_completed(dest,job['config']['declared_config_sha256']))

    def test_wrong_destination_never_overwrites_another_job_or_prunes_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);a,job_a,r_a=self.prepare(base,'first');b,_,r_b=self.prepare(base,'second','cnn')
            dest=base/'results/first';export_and_prune(a,dest,base/'work',r_a,prune=False)
            original={p.name:p.read_bytes() for p in dest.iterdir()}
            with self.assertRaisesRegex(RuntimeError,'another job'):export_and_prune(b,dest,base/'work',r_b)
            self.assertEqual(original,{p.name:p.read_bytes() for p in dest.iterdir()});self.assertTrue(b.exists())

    def test_incomplete_durable_journal_is_not_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root,_,receipt=self.prepare(base,'first')
            receipt['records']=receipt['records'][:1]
            with self.assertRaisesRegex(RuntimeError,'journal'):export_and_prune(root,base/'results/first',base/'work',receipt)
            self.assertTrue(root.exists());self.assertFalse((base/'results/first').exists())

    def test_two_controller_jobs_are_archived_separately_and_completed_jobs_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);pack=base/'pack';work=base/'work';cache=base/'cache'
            manifest=build_pack(pack);dump(cache/'cifar10/receipt.json',{})
            datasets={'cifar10':{}};dump(pack/'data_snapshot.json',dict(datasets=datasets,sha256=digest(dict(datasets=datasets))))
            def provision(root,cfg,source):
                root.mkdir();job=dict(config=cfg,job_id=digest(cfg),source_hash='fixture')
                dump(root/'public_job.json',job);(root/'.experiment-pack-owned').write_text(job['job_id']);return root
            def launch(root):
                job=json.loads((root/'public_job.json').read_text());records=[dict(round=n,seconds=float(n)) for n in (1,2)]
                dump(root/'coordinator/journal.json',dict(job_id=job['job_id'],completed=2,records=records,pending=None))
                return dict(status='completed',job_id=job['job_id'],completed_rounds=2,records=records)
            profile=dict(GPU_available=True,landlock_abi=4,GPU=dict(memory=24*1024**3))
            with patch('experiment_pack.controller.gpu_preflight',return_value=profile),patch('experiment_pack.provision.provision',side_effect=provision),patch('experiment_pack.launch.launch',side_effect=launch) as training:
                state=execute(pack,work,cache)
                ids=[j['id'] for j in manifest['jobs'] if j['config']['workflow']=='gpu_gate']
                self.assertEqual(set(state['completed']),set(ids));self.assertEqual(training.call_count,2)
                self.assertEqual({p.name for p in (pack/'results').iterdir()},set(ids))
                self.assertEqual({json.loads((pack/'results'/i/'public_job.json').read_text())['config']['model'] for i in ids},{'mlp','cnn'})
                execute(pack,work,cache);self.assertEqual(training.call_count,2)
                with self.assertRaisesRegex(RuntimeError,'calibration exceeds'):
                    execute(pack,work,cache,until='tuning',max_estimated_hours=.001)
                self.assertEqual(training.call_count,2)
                (pack/'results'/ids[0]/'verification.json').unlink()
                with self.assertRaisesRegex(RuntimeError,'never retrain'):execute(pack,work,cache)
                self.assertEqual(training.call_count,2)
                self.assertEqual(json.loads((pack/'state.json').read_text())['archive_review_required'],[ids[0]])

if __name__=='__main__':unittest.main()
