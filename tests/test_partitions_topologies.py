"""Partition integrity, graph semantics and runner integration regressions."""
import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import networkx as nx
import numpy as np
import torch
from torch.utils.data import Dataset, Subset
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from data_utils import create_client_loaders, create_dirichlet_client_loaders
from topology import build_topology
from main import parse_args, validate_args, build_blockchain_configuration
from run_validation_experiments import ValidationExperiment, command_for, build_grouped_summary, summarize_run
import pandas as pd


class Labels(Dataset):
    def __init__(self):
        self.targets = torch.arange(10000) % 10
    def __len__(self):
        return len(self.targets)
    def __getitem__(self, i):
        return torch.zeros(1, 28, 28), self.targets[i]


class PartitionTests(unittest.TestCase):
    def test_dirichlet_no_loss_no_overlap_subset_reproducible(self):
        data = Subset(Labels(), list(range(17, 9017)))
        for alpha in [0.1, 0.5, 1.0]:
            a = create_dirichlet_client_loaders(data, 10, 32, alpha, 7)
            b = create_dirichlet_client_loaders(data, 10, 32, alpha, 7)
            indices = [i for c in a for i in c.dataset.indices]
            self.assertEqual(sorted(indices), list(range(len(data))))
            self.assertGreaterEqual(min(len(c.dataset) for c in a), 10)
            self.assertEqual([c.dataset.indices for c in a], [c.dataset.indices for c in b])
            self.assertNotEqual([c.dataset.indices for c in a], [c.dataset.indices for c in create_dirichlet_client_loaders(data, 10, 32, alpha, 8)])

    def test_alpha_changes_observed_label_skew(self):
        data = Labels()
        def entropy(alpha):
            loaders = create_dirichlet_client_loaders(data, 10, 32, alpha, 1)
            result = []
            for c in loaders:
                counts = np.bincount(data.targets[c.dataset.indices].numpy(), minlength=10)
                p = counts[counts > 0] / counts.sum()
                result.append(-(p * np.log(p)).sum())
            return np.mean(result)
        self.assertGreater(entropy(100), entropy(0.1))

    def test_invalid_partition_fails_explicitly(self):
        for kw in [{"alpha": 0}, {"alpha": float('nan')}, {"min_samples": 1001}, {"num_clients": 0}]:
            args = dict(train_dataset=Labels(), num_clients=10, batch_size=32)
            args.update(kw)
            with self.assertRaises(ValueError):create_dirichlet_client_loaders(**args)
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            create_client_loaders(Labels(), 5, 32, 'typo')


class TopologyTests(unittest.TestCase):
    def test_incomplete_or_nonfinite_runs_cannot_be_summarized(self):
        experiment=ValidationExperiment(seed=1,dataset='cifar10',num_clients=5,topology='ring',
            split_type='dirichlet',security_mode='none',num_rounds=2,batch_size=32,
            adaptive_policy='topk_risk',adaptive_he_target_ratio=0.4)
        frame=pd.DataFrame({'round':[1,2],'avg_test_accuracy':[10.,20.],
                            'avg_test_loss':[2.3,2.2],'avg_train_loss':[2.,1.9]})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'metrics.csv'
            frame.to_csv(path,index=False)
            self.assertEqual(summarize_run(path,experiment)['final_accuracy_percent'],20.)
            frame.iloc[:1].to_csv(path,index=False)
            with self.assertRaises(ValueError):summarize_run(path,experiment)
            frame.loc[1,'avg_test_accuracy']=float('nan')
            frame.to_csv(path,index=False)
            with self.assertRaises(ValueError):summarize_run(path,experiment)

    def test_new_graphs_connected_undirected_exact_client_count(self):
        for n in [4, 5, 6, 10, 20]:
            for topology in ['caveman', 'barabasi_albert']:
                adj = build_topology(topology, n, 42)
                self.assertEqual(set(adj), set(range(n)))
                self.assertTrue(nx.is_connected(nx.Graph(adj)))
                for a, peers in adj.items():
                    self.assertNotIn(a, peers)
                    self.assertEqual(len(peers), len(set(peers)))
                    for b in peers:self.assertIn(a, adj[b])
                self.assertEqual(adj, build_topology(topology, n, 42))
        self.assertNotEqual(build_topology('barabasi_albert', 20, 1), build_topology('barabasi_albert', 20, 2))

    def test_graph_definitions(self):
        graph = nx.Graph(build_topology('caveman', 12, 42, caveman_cliques=3))
        self.assertTrue(nx.is_isomorphic(graph, nx.connected_caveman_graph(3, 4)))
        graph = nx.Graph(build_topology('barabasi_albert', 10, 42, barabasi_m=2))
        self.assertEqual(set(graph.edges), set(nx.barabasi_albert_graph(10, 2, seed=42).edges))
        self.assertEqual(graph.number_of_edges(), 16)
        for args in [('typo',5),('caveman',3),('barabasi_albert',2)]:
            with self.assertRaises(ValueError):build_topology(*args)

    def test_cli_and_metadata_route_parameters(self):
        with patch.object(sys, 'argv', ['main.py','--split_type','dirichlet','--dirichlet_alpha','0.1','--topology','barabasi_albert','--barabasi_m','3']):
            args = parse_args()
        validate_args(args)
        meta = build_blockchain_configuration(args, 'cpu')
        self.assertEqual((meta['dirichlet_alpha'], meta['barabasi_m']), (0.1, 3))

    def test_validation_names_parameters_distinct(self):
        base = dict(seed=1,dataset='cifar10',num_clients=5,topology='caveman',split_type='dirichlet',security_mode='none',num_rounds=20,batch_size=32,adaptive_policy='topk_risk',adaptive_he_target_ratio=0.4)
        a=ValidationExperiment(**base,dirichlet_alpha=0.5)
        b=ValidationExperiment(**base,dirichlet_alpha=0.5000001)
        self.assertNotEqual(a.name,b.name)
        cmd=command_for(a,Path('main.py'))
        self.assertEqual(cmd[cmd.index('--dirichlet_alpha')+1],'0.5')
        # Distinct alphas must never pool into one statistical group.
        from run_validation_experiments import RUN_SUMMARY_COLUMNS
        rows=[]
        for alpha in [0.1,0.5]:
            row={c:0.0 for c in RUN_SUMMARY_COLUMNS}
            row.update(security_mode='none',dataset='cifar10',split_type='dirichlet',topology='ring',num_clients=5,dirichlet_alpha=alpha,execution_profile='cached_gpu')
            rows.append(row)
        self.assertEqual(len(build_grouped_summary(pd.DataFrame(rows))),2)


if __name__ == '__main__':unittest.main()
