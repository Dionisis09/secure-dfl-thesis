"""Launch one independently provisioned client. Never launched by the trainer."""
import argparse
import json
import os
import sys
from pathlib import Path


def main():
    os.umask(0o077)
    for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:
        os.environ[name]='1'
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
    from independent_clients.isolation import protect_memory,restrict_files
    protect_memory()  # before reading private enrollment/training secrets
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    args=parser.parse_args();path=Path(args.config).resolve();config=json.loads(path.read_text())
    root=Path(config['private_dir']).resolve()
    if path.parent!=root:raise RuntimeError('client config must be inside its private directory')
    os.environ['TMPDIR']=str(root/'tmp');(root/'tmp').mkdir(exist_ok=True)
    os.environ['XDG_CACHE_HOME']=str(root/'cache');os.environ['CUDA_CACHE_PATH']=str(root/'cache'/'cuda')
    (root/'cache'/'cuda').mkdir(parents=True,exist_ok=True)
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    sys.dont_write_bytecode=True
    native=os.environ.get('DFL_RANGE_LIB')
    if not native:raise RuntimeError('DFL_RANGE_LIB is required')
    isolation=restrict_files(root,[native],gpu=config['device']=='cuda',bind_ports=[config['port']])
    # Confinement precedes third-party libraries and any of their native threads.
    from independent_clients.service import ClientService
    from independent_clients.network import serve
    from independent_clients.common import run_lock
    with run_lock(root/'service.lock'):
        service=ClientService(config,isolation=isolation)
        serve(service,config)


if __name__=='__main__':main()
