"""Explicit overnight commands; start runs calibration/admission/training in order."""
import argparse
import json
import os
import sys
from pathlib import Path
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import overnight8 as study

p=argparse.ArgumentParser()
p.add_argument('command', choices=('prepare','start','status','plan','summarize','pause','clear-pause'))
p.add_argument('--pack', default=study.PACK_NAME)
p.add_argument('--cache', default='data/simulator50-cache')
a=p.parse_args()
pack=Path(a.pack)
if a.command in ('prepare','start'):
    result=getattr(study,a.command)(pack,a.cache)
elif a.command in ('pause','clear-pause'):
    study.checked(pack)
    if a.command=='pause':
        (pack/'pause.request').touch()
        result=dict(status='pause_requested_after_current_round')
    else:
        pack=pack.resolve()
        for path in [pack/'pause.request',*pack.glob('calibration/cal-*/pause.request'),*pack.glob('results/sim-*/pause.request')]:
            assert path.resolve().is_relative_to(pack)
            if path.exists():path.unlink()
        result=dict(status='pause_flags_cleared_no_training_started_deadline_unchanged')
else:
    result=getattr(study,a.command)(pack)
if a.command=='prepare':result=dict(status='prepared_not_started',candidate_runs=result['candidate_jobs'])
if a.command=='summarize':result=dict(status=result['status'],groups=len(result['groups']))
print(json.dumps(result,indent=2))
