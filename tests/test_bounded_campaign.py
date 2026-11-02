import sys
from pathlib import Path
from collections import defaultdict,Counter
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from run_extended_campaign import make_plan
from run_bounded_campaign import selected

class BoundedScope(unittest.TestCase):
    def test_scope_has_complete_seed_trios_and_unchanged_training(self):
        jobs=[j for j in make_plan() if selected(j)]
        self.assertEqual(len(jobs),228)
        groups=defaultdict(list)
        for j in jobs:
            key=tuple(j[k] for k in ['dataset','num_clients','split_type','dirichlet_alpha','topology','security_mode'])
            groups[key].append(j['seed'])
            self.assertEqual(j['num_rounds'],20)
            self.assertEqual(j['batch_size'],32)
            self.assertEqual(j['execution_profile'],'cached_gpu')
        self.assertEqual(len(groups),76)
        self.assertTrue(all(sorted(seeds)==[1,2,3] for seeds in groups.values()))
        self.assertEqual(Counter(j['dataset'] for j in jobs),{'cifar10':108,'fashion_mnist':60,'mnist':60})

if __name__=='__main__':unittest.main()
