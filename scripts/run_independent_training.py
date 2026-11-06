"""Aggregate-only coordinator; cannot load client shards or client checkpoints."""
import argparse
import json
import os
import sys
from pathlib import Path


def main():
    os.umask(0o077);os.environ['CUDA_VISIBLE_DEVICES']='';os.environ['PYTHONDONTWRITEBYTECODE']='1'
    for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:
        os.environ[name]='1'
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
    from independent_clients.isolation import protect_memory,restrict_files,denied_probes
    protect_memory()
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    parser.add_argument('--max-new-rounds',type=int,default=0)
    parser.add_argument('--verify-boundary',action='store_true')
    parser.add_argument('--stop-after-commit-intent',action='store_true',help='Pause after durable global commit intent, before client commit messages')
    args=parser.parse_args();path=Path(args.config).resolve();config=json.loads(path.read_text())
    root=Path(config['private_dir']).resolve()
    if path.parent!=root or args.max_new_rounds<0:raise RuntimeError('invalid coordinator policy')
    os.environ['TMPDIR']=str(root/'tmp');(root/'tmp').mkdir(exist_ok=True)
    isolation=restrict_files(root,connect_ports=[entry['port'] for entry in config['endpoints'].values()])
    from independent_clients.coordinator import execute
    from independent_clients.common import atomic_json
    if args.verify_boundary:
        probes=config.get('boundary_probes',{})
        if not probes.get('paths') or not probes.get('pids'):raise RuntimeError('boundary probe fixtures missing')
        isolation['denial_probes']=denied_probes(probes['paths'],probes['pids'])
        atomic_json(root/'boundary_probe.json',isolation)
    tests=[('get_state',{}),('get_optimizer',{}),('debug',{}),('test_forge',{}),
           ('train',dict(round=1,epoch='0'*32,base='invalid-base'))] if args.verify_boundary else []
    execute(config,isolation=isolation,max_new_rounds=args.max_new_rounds,probes=tests,stop_after_commit_intent=args.stop_after_commit_intent)


if __name__=='__main__':main()
