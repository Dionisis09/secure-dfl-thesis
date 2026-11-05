"""Parameter-budget matched models; both expose head.weight[10,256]+head.bias."""
import math
from torch import nn

def block(a,b):return nn.Sequential(nn.Conv2d(a,b,3,padding=1,bias=False),nn.BatchNorm2d(b),nn.ReLU(inplace=True))
class Residual(nn.Module):
    def __init__(self,n):super().__init__();self.layers=nn.Sequential(block(n,n),block(n,n))
    def forward(self,x):return x+self.layers(x)
class DeterministicGlobalMax(nn.Module):
    """Same global maximum/first-tie selection, with deterministic CUDA backward."""
    def forward(self,x):return x.flatten(2).max(dim=2,keepdim=True).values.unsqueeze(-1)
class ResidualCNN(nn.Module):
    def __init__(self,input_shape=(3,32,32),num_classes=10):
        super().__init__()
        self.features=nn.Sequential(block(input_shape[0],32),block(32,64),nn.MaxPool2d(2),Residual(64),block(64,128),nn.MaxPool2d(2),block(128,256),nn.MaxPool2d(2),Residual(256),DeterministicGlobalMax())
        self.head=nn.Linear(256,num_classes)
    def forward(self,x):return self.head(self.features(x).flatten(1))
class BudgetMatchedMLP(nn.Module):
    def __init__(self,input_shape=(3,32,32),num_classes=10):
        super().__init__();features=math.prod(input_shape)
        target=sum(p.numel() for p in ResidualCNN(input_shape,num_classes).parameters())
        def count(h):return (features+1)*h+2*h+(h+1)*256+512+(256+1)*num_classes
        self.hidden_width=min(range(128,2049,16),key=lambda h:abs(count(h)-target))
        self.features=nn.Sequential(nn.Flatten(),nn.Linear(features,self.hidden_width),nn.LayerNorm(self.hidden_width),nn.GELU(),nn.Linear(self.hidden_width,256),nn.LayerNorm(256),nn.GELU())
        self.head=nn.Linear(256,num_classes)
    def forward(self,x):return self.head(self.features(x))
def build_model(name,input_shape,num_classes=10):
    if name not in ('mlp','cnn'):raise ValueError('model must be mlp or cnn')
    return (BudgetMatchedMLP if name=='mlp' else ResidualCNN)(input_shape,num_classes)
