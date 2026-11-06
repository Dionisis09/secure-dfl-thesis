"""Source-backed mean/sample SD: incomplete seeds have no inferential statistics."""
import json,statistics
from pathlib import Path
from .controller import verify_completed,dump

def summarize(pack):
    pack=Path(pack);manifest=json.loads((pack/'manifest.json').read_text());groups={};pending=0
    for j in manifest['jobs']:
        cfg=j['config']
        if cfg['workflow'] not in ('validation','sensitivity','network'):continue
        key=tuple(cfg[n] for n in ('workflow','model','dataset','split','dirichlet_alpha','topology','mode','requested_HE_ratio'))
        folder=pack/'results'/j['id']
        if not verify_completed(folder,j['config_sha256']):pending+=1;continue
        receipt=json.loads((folder/'verification.json').read_text())
        row=receipt['records'][-1];profile=receipt.get('runtime_profile_sha256','unrecorded')
        groups.setdefault((key,profile),[]).append(dict(seed=cfg['seed'],job=j['id'],metrics=row['metrics'],wall=receipt['supervisor_wall_seconds']))
    result=[]
    for (key,profile),rows in sorted(groups.items(),key=lambda x:str(x[0])):
        seeds={r['seed'] for r in rows};complete=seeds=={1,2,3} and len(rows)==3
        item=dict(context=list(key),runtime_profile=profile,seeds=sorted(seeds),n=len(rows),complete_three_seed_group=complete,source_jobs=[r['job'] for r in rows],statistics=None)
        if complete:
            stats={}
            for metric in ('test_final_accuracy','test_best_accuracy','test_final_loss','test_best_loss','best_validation_accuracy'):
                values=[r['metrics'][metric] for r in rows]
                if all(v is not None for v in values):stats[metric]=dict(mean=statistics.mean(values),sample_SD=statistics.stdev(values))
            values=[r['wall'] for r in rows];stats['wall_seconds']=dict(mean=statistics.mean(values),sample_SD=statistics.stdev(values))
            item['statistics']=stats
        result.append(item)
    value=dict(pending_jobs=pending,groups=result,accuracy_SD_unit='percentage points',time_profiles_never_pooled=True,historical_results_included=False)
    dump(pack/'summary.json',value);return value
