"""Explicit role entry point; does not provision or launch another client's data."""
import argparse,os,sys
from pathlib import Path
def main():
    os.umask(0o077);sys.dont_write_bytecode=True
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
    p=argparse.ArgumentParser();p.add_argument('--role',choices=['client','coordinator','gpu_worker'],required=True);p.add_argument('--config',required=True);p.add_argument('--max-new-rounds',type=int,default=0);p.add_argument('--preflight-only',action='store_true');args=p.parse_args()
    if args.max_new_rounds<0:p.error('max-new-rounds must be nonnegative')
    os.environ['CUDA_VISIBLE_DEVICES']='0' if args.role=='gpu_worker' else ''
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
    from experiment_pack.runtime import role_main
    role_main(args)
if __name__=='__main__':main()
