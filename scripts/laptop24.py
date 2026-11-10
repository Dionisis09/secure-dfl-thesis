"""Prepare/measure explicitly; run starts the scientific series only on request."""
import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import laptop24

parser = argparse.ArgumentParser()
parser.add_argument('command', choices=('prepare', 'preflight', 'calibrate', 'plan', 'status', 'run', 'summarize', 'pause', 'clear-pause'))
parser.add_argument('--pack', default=laptop24.PACK_NAME)
parser.add_argument('--cache', default='data/simulator50-cache')
args = parser.parse_args()
pack = Path(args.pack)

if args.command == 'prepare':
    result = laptop24.prepare(pack, args.cache)
    print(json.dumps(dict(status='prepared_not_started', candidate_jobs=result['candidate_jobs'], required_jobs=60)))
elif args.command in ('preflight', 'calibrate', 'run'):
    result = getattr(laptop24, args.command)(pack, args.cache)
    print(json.dumps(result if result is not None else laptop24.status(pack)))
elif args.command in ('pause', 'clear-pause'):
    laptop24.checked(pack)
    if args.command == 'pause':
        (pack / 'pause.request').touch()
        print('Pause requested; current round saves its atomic checkpoint.')
    else:
        pack = pack.resolve()
        for path in [pack / 'pause.request', *pack.glob('calibration/cal-*/pause.request'), *pack.glob('results/sim-*/pause.request')]:
            assert path.resolve().is_relative_to(pack)
            if path.exists():
                path.unlink()
        print('Pause flags cleared; no training started; original24hour deadline preserved.')
else:
    result = getattr(laptop24, args.command)(pack)
    if args.command == 'summarize':
        result = dict(status=result['status'], groups=len(result['groups']))
    print(json.dumps(result, indent=2))
