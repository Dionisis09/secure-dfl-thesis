import copy,os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

class TrainingIntegrationTests(unittest.TestCase):
    def test_deterministic_global_max_matches_forward_and_first_tie_gradient(self):
        import torch
        from matched_models import DeterministicGlobalMax
        old_flag=torch.are_deterministic_algorithms_enabled()
        try:
            torch.use_deterministic_algorithms(True)
            for values in [torch.zeros(2,3,4,5),(torch.arange(120).reshape(2,3,4,5)%7-3).float()]:
                reference=values.clone().requires_grad_();expected=torch.nn.functional.adaptive_max_pool2d(reference,1)
                gradient=torch.arange(1,7).float().reshape(2,3,1,1);expected.backward(gradient)
                for device in ['cpu']+(['cuda'] if torch.cuda.is_available() else []):
                    actual=values.to(device).detach().requires_grad_();output=DeterministicGlobalMax()(actual);output.backward(gradient.to(device))
                    torch.testing.assert_close(output.cpu(),expected,rtol=0,atol=0)
                    torch.testing.assert_close(actual.grad.cpu(),reference.grad,rtol=0,atol=0)
        finally:torch.use_deterministic_algorithms(old_flag)
    def test_model_budgets_and_shared_classifier(self):
        import torch
        from matched_models import build_model
        torch.set_num_threads(1)
        mlp=build_model('mlp',(3,32,32));cnn=build_model('cnn',(3,32,32))
        self.assertEqual(sum(p.numel() for p in mlp.parameters()),1655514)
        self.assertEqual(sum(p.numel() for p in cnn.parameters()),1646122)
        for model in (mlp,cnn):
            self.assertEqual(tuple(model.head.weight.shape),(10,256));self.assertEqual(tuple(model.head.bias.shape),(10,))
            logits=model(torch.zeros(2,3,32,32));self.assertEqual(tuple(logits.shape),(2,10))
    def test_real_sgd_update_full_state_protected_and_exact(self):
        from secure_protocol_v6 import rangeproof as rp
        from secure_protocol_v4.core import Rejected
        try:rp.info()
        except Rejected:
            if os.environ.get('DFL_REQUIRE_NATIVE')=='1':raise
            self.skipTest('native Bulletproofs build required')
        import torch
        from torch import nn
        from torch.utils.data import TensorDataset,DataLoader
        from client import Client
        from secure_protocol_v6.training_adapter import secure_average,state_hash
        class Tiny(nn.Module):
            def __init__(self):super().__init__();self.features=nn.Sequential(nn.Linear(4,256),nn.ReLU());self.head=nn.Linear(256,10)
            def forward(self,x):return self.head(self.features(x))
        torch.set_num_threads(1);torch.manual_seed(9);initial=Tiny();base={n:v.clone() for n,v in initial.state_dict().items()};states=[]
        for i in range(3):
            dataset=TensorDataset(torch.randn(4,4),torch.tensor([i,i+1,i+2,i+3]))
            client=Client(i,copy.deepcopy(initial),DataLoader(dataset,batch_size=4),'cpu',.01)
            client.train_local(1);states.append(client.get_state_dict())
        saved=[state_hash(s) for s in states]
        result,receipt,control=secure_average(states,base,run='trained-unit',round_number=1,model_id='tiny-real-sgd')
        self.assertEqual(state_hash(result),state_hash(control));self.assertNotEqual(state_hash(result),state_hash(base))
        self.assertEqual([state_hash(s) for s in states],saved)
        self.assertTrue(receipt['range_proofs_required']);self.assertEqual(receipt['quantized_control_max_integer_error'],0)
        self.assertEqual(receipt['backbone_values'],1280)
if __name__=='__main__':unittest.main()
