"""Separate exploratory CIFAR-10 ablations; never merge with the 402-run campaign."""
import argparse
import gc
import hashlib
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import torch
from main import parse_args as training_args, run_experiment


CASES = [
    ("shards_ring_40r", "non_iid", "ring", 0.5, 40),
    ("iid_ring_40r", "iid", "ring", 0.5, 40),
    ("shards_full_20r", "non_iid", "fully_connected", 0.5, 20),
    ("dir01_ring_20r", "dirichlet", "ring", 0.1, 20),
    ("dir05_ring_20r", "dirichlet", "ring", 0.5, 20),
    ("dir10_ring_20r", "dirichlet", "ring", 1.0, 20),
    ("dir05_caveman_20r", "dirichlet", "caveman", 0.5, 20),
    ("dir05_barabasi_20r", "dirichlet", "barabasi_albert", 0.5, 20),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution_profile', choices=['cached_gpu','cached_cpu','legacy'],default='cached_gpu')
    parser.add_argument('--seeds',default='1')
    parser.add_argument('--output_dir', default='results/campaign_20261020_extension')
    parser.add_argument('--dry_run',action='store_true')
    parser.add_argument('--resume',action='store_true')
    cli=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    output=Path(cli.output_dir)
    if not output.is_absolute():output=root/output
    seeds=list(dict.fromkeys(int(s) for s in cli.seeds.split(',')))
    if not seeds or any(s < 0 for s in seeds):raise ValueError('seeds must be nonnegative integers')
    plan=[dict(case=case,split_type=split,topology=topology,dirichlet_alpha=alpha,
               num_rounds=rounds,seed=seed,dataset='cifar10',num_clients=5,
               batch_size=32,lr=0.01,local_epochs=1,security_mode='none',
               execution_profile=cli.execution_profile,caveman_cliques=2,barabasi_m=2)
          for seed in seeds for case,split,topology,alpha,rounds in CASES]
    if cli.dry_run:
        print(json.dumps(plan,indent=2));return
    existing_plan = (output/'plan.json').exists()
    if existing_plan:
        if not cli.resume or json.loads((output/'plan.json').read_text()) != plan:
            raise ValueError('Output already has a plan; use --resume for exactly the same configuration')
    output.mkdir(parents=True,exist_ok=True)
    (output/'plan.json').write_text(json.dumps(plan,indent=2))
    if not existing_plan:
        (output/'source_sha256.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root/'src').glob('*.py')},indent=2))
    records=[]
    for index,spec in enumerate(plan,1):
        name=f"extension_20261020_{spec['case']}_seed{spec['seed']}"
        if output.name != 'campaign_20261020_extension':
            name += '_'+hashlib.sha256(output.name.encode()).hexdigest()[:8]
        if cli.execution_profile != 'cached_gpu':name+=f'_{cli.execution_profile}'
        csv=output/f'{name}_metrics.csv'
        print(f'[{index}/{len(plan)}] {name}',flush=True)
        if not (cli.resume and csv.exists()):
            argv=['main.py','--dataset','cifar10','--num_clients','5','--num_rounds',str(spec['num_rounds']),
                  '--split_type',spec['split_type'],'--topology',spec['topology'],
                  '--dirichlet_alpha',str(spec['dirichlet_alpha']),
                  '--execution_profile',cli.execution_profile,'--seed',str(spec['seed']),
                  '--experiment_name',name,'--diagnostics']
            if cli.execution_profile=='cached_cpu':argv.extend(['--device','cpu'])
            with patch.object(sys,'argv',argv):args=training_args()
            run_experiment(args)
            for kind in ['metrics.csv','metadata.json','diagnostics.json']:
                shutil.copy2(root/'results/logs'/f'{name}_{kind}',output/f'{name}_{kind}')
            gc.collect()
            if torch.cuda.is_available():torch.cuda.empty_cache()
        frame=pd.read_csv(csv)
        if len(frame)!=spec['num_rounds']:raise ValueError(f'Incomplete run: {csv}')
        final=frame.iloc[-1]
        records.append({**spec,'experiment_name':name,
                        'accuracy_round20':float(frame.loc[frame['round']==20,'avg_test_accuracy'].iloc[0]),
                        'final_accuracy':float(final.avg_test_accuracy),
                        'final_test_loss':float(final.avg_test_loss),
                        'round1_accuracy':float(frame.iloc[0].avg_test_accuracy),
                        'final_5_round_improvement':float(final.avg_test_accuracy-frame.iloc[-6].avg_test_accuracy)})
        pd.DataFrame(records).to_csv(output/'summary.csv',index=False)
        (output/'progress.json').write_text(json.dumps({'completed':index,'planned':len(plan)},indent=2))
    print(f'Completed {len(records)} exploratory runs. Evidence: {output}',flush=True)


if __name__=='__main__':main()
