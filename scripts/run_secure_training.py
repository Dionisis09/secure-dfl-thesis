"""Explicit opt-in runner for proved MLP/CNN experiments; legacy runs unchanged."""
import argparse,os,sys
from pathlib import Path
def main():
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',choices=['mlp','cnn'],required=True);parser.add_argument('--dataset',choices=['mnist','fashion_mnist','cifar10'],default='cifar10')
    parser.add_argument('--data-dir',default='data');parser.add_argument('--data-archive');parser.add_argument('--output',required=True)
    parser.add_argument('--clients',type=int,default=20);parser.add_argument('--rounds',type=int,default=2);parser.add_argument('--local-epochs',type=int,default=1)
    parser.add_argument('--batch-size',type=int,default=32);parser.add_argument('--learning-rate',type=float,default=.01);parser.add_argument('--seed',type=int,default=1)
    parser.add_argument('--split',choices=['iid','non_iid','dirichlet'],default='iid');parser.add_argument('--alpha',type=float,default=.5)
    parser.add_argument('--train-samples',type=int,default=0);parser.add_argument('--test-samples',type=int,default=0)
    parser.add_argument('--head-bound',type=float,default=1.);parser.add_argument('--parallelism',type=int,default=8);parser.add_argument('--device',choices=['auto','cpu','cuda'],default='auto')
    parser.add_argument('--resume',action='store_true');parser.add_argument('--max-new-rounds',type=int,default=0)
    parser.add_argument('--preflight-only',action='store_true',help='Validate data/backend/models and save round-zero checkpoint without training')
    from secure_training import execute
    execute(parser.parse_args())
if __name__=='__main__':main()
