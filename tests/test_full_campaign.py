"""Coverage checks for the user-approved full experiment grid."""
from collections import Counter,defaultdict
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from run_extended_campaign import make_plan


class FullCampaign(unittest.TestCase):
    def test_exact_grid_three_seeds_and_all_modes(self):
        plan=make_plan()
        self.assertEqual(len(plan),1440)
        self.assertEqual(len({j['id'] for j in plan}),1440)
        self.assertEqual(sum(j['split_type']=='dirichlet' for j in plan),1080)
        self.assertEqual(Counter(j['seed'] for j in plan),{1:480,2:480,3:480})
        groups=defaultdict(list)
        for j in plan:
            key=tuple(j[k] for k in ['dataset','num_clients','topology','split_type','dirichlet_alpha','security_mode'])
            groups[key].append(j['seed'])
            self.assertEqual(j['num_rounds'],20)
            self.assertEqual(j['execution_profile'],'cached_gpu')
            self.assertNotIn('..',j['metrics_path'])
        self.assertEqual(len(groups),480)
        self.assertTrue(all(sorted(v)==[1,2,3] for v in groups.values()))


if __name__=='__main__':unittest.main()
