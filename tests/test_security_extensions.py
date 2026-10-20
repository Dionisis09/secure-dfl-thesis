"""Real training and CKKS smoke tests on the new graph/partition combinations."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import torch
from torch.utils.data import Dataset
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import main
from config import Config
from data_utils import get_dataset_spec


class TinyRGB(Dataset):
    def __init__(self):
        g=torch.Generator().manual_seed(77)
        self.images=torch.rand((150,3,32,32),generator=g)
        self.targets=torch.arange(150)%10
    def __len__(self):return len(self.targets)
    def __getitem__(self,i):return self.images[i],int(self.targets[i])


class ProtectedExtensions(unittest.TestCase):
    def test_all_security_modes_match_plain_new_topologies(self):
        data=TinyRGB()
        threads=torch.get_num_threads()
        torch.set_num_threads(1)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                for topology in ['caveman','barabasi_albert']:
                    baseline=None
                    for mode in ['none','masking','pairwise_masking','selective_he','adaptive_hybrid']:
                        with self.subTest(topology=topology,mode=mode), ExitStack() as stack:
                            stack.enter_context(redirect_stdout(io.StringIO()))
                            stack.enter_context(redirect_stderr(io.StringIO()))
                            argv=['main.py','--dataset','cifar10','--num_clients','5','--num_rounds','2',
                                  '--device','cpu','--split_type','dirichlet','--dirichlet_min_samples','2',
                                  '--topology',topology,'--security_mode',mode,'--experiment_name',mode]
                            if mode=='none':argv.append('--diagnostics')
                            stack.enter_context(patch.object(sys,'argv',argv))
                            args=main.parse_args()
                            stack.enter_context(patch.object(main,'Config',return_value=Config(results_dir=tmp)))
                            stack.enter_context(patch.object(main,'get_datasets',return_value=(data,data,get_dataset_spec('cifar10'))))
                            for plot in ['plot_accuracy','plot_loss','plot_round_time','plot_communication']:
                                stack.enter_context(patch.object(main,plot))
                            log=main.run_experiment(args)
                            result=log.metrics[-1]
                            self.assertTrue(json.loads((Path(tmp)/f'logs/{mode}_metadata.json').read_text())['partition_complete'])
                            if baseline is None:
                                baseline=result
                                diag=json.loads((Path(tmp)/f'logs/{mode}_diagnostics.json').read_text())
                                self.assertEqual(len(diag['per_client']),5)
                            else:
                                self.assertAlmostEqual(result['avg_test_loss'],baseline['avg_test_loss'],places=5)
                                self.assertEqual(result['avg_test_accuracy'],baseline['avg_test_accuracy'])
        finally:torch.set_num_threads(threads)


if __name__=='__main__':unittest.main()
