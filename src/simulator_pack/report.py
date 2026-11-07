import json,statistics
from pathlib import Path
from .design import atomic,validate
from .engine import completed

def summarize(pack):
    pack=Path(pack);manifest=validate(json.loads((pack/'manifest.json').read_text()));groups={};pending=0
    for b in manifest['bundles']:
        for j in b['jobs']:
            cfg=j['config'];folder=pack/'results'/j['id']
            if not completed(folder,cfg):pending+=1;continue
            r=json.loads((folder/'complete.json').read_text())
            key=tuple(cfg[n] for n in ('model','dataset','split','alpha','topology','mode','HE_ratio','stage'))+(r['runtime_sha256'],)
            groups.setdefault(key,[]).append(r)
    rows=[]
    for key,items in sorted(groups.items(),key=lambda x:str(x[0])):
        complete=len(items)==3 and {r['config']['seed'] for r in items}=={1,2,3}
        row=dict(context=list(key),n=len(items),seeds=sorted(r['config']['seed'] for r in items),complete_three_seed_group=complete,statistics=None)
        if complete:
            row['statistics']={}
            for metric in ('accuracy','loss'):
                values=[r['final_test'][metric] for r in items];row['statistics']['final_test_'+metric]=dict(mean=statistics.mean(values),sample_SD=statistics.stdev(values))
            values=[r['best_validation_test']['accuracy'] for r in items];row['statistics']['best_validation_test_accuracy']=dict(mean=statistics.mean(values),sample_SD=statistics.stdev(values))
        rows.append(row)
    value=dict(candidate_jobs=manifest['candidate_jobs'],verified_completed=sum(len(v) for v in groups.values()),candidate_pending_or_unselected=pending,groups=rows,
        historical_results_included=False,threat_model='trusted_single_process_simulator',time_profiles_never_pooled=True,accuracy_SD_unit='percentage points')
    atomic(pack/'summary.json',value);return value
