import json,statistics
from pathlib import Path
from .design import atomic,validate,digest
from .engine import completed

def summarize(pack):
    pack=Path(pack);manifest=validate(json.loads((pack/'manifest.json').read_text()));groups={};pending=0;receipts={}
    source=json.loads((pack/'source_snapshot.json').read_text())['hash']
    data=json.loads((pack/'data_snapshot.json').read_text())['datasets'] if (pack/'data_snapshot.json').exists() else {}
    selection=json.loads((pack/'selected_plan.json').read_text()) if (pack/'selected_plan.json').exists() else None
    if selection and selection['sha256']!=digest({k:v for k,v in selection.items() if k!='sha256'}):raise RuntimeError('selected plan hash mismatch')
    for b in manifest['bundles']:
        for j in b['jobs']:
            cfg=j['config'];folder=pack/'results'/j['id']
            expected_data=data.get(cfg['dataset'],{}).get('receipt_sha256')
            if not completed(folder,cfg,source,selection['runtime_sha256'] if selection else None,expected_data):pending+=1;continue
            r=json.loads((folder/'complete.json').read_text())
            if r['runtime_sha256']!=digest(r['runtime_profile']):raise RuntimeError('result runtime provenance differs')
            if manifest.get('scaling'):
                from .campaign import require_target
                require_target(manifest,r['runtime_profile'])
            receipts[j['id']]=r
            key=tuple(cfg[n] for n in ('clients','model','dataset','split','alpha','topology','mode','HE_ratio','stage'))+(r['runtime_sha256'],r['source_hash'],r['data_receipt_sha256'])
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
    if manifest.get('scaling'):
        spec=manifest['scaling'];ids=spec['new_job_ids']+spec['reference_50_job_ids'];scaling_groups={};comparisons=[]
        for identifier in ids:
            if identifier not in receipts:continue
            r=receipts[identifier];c=r['config'];key=(c['clients'],c['model'],c['mode'],r['runtime_sha256'])
            scaling_groups.setdefault(key,[]).append((identifier,r))
        for key,items in sorted(scaling_groups.items()):
            complete=len(items)==3 and {r['config']['seed'] for _,r in items}=={1,2,3}
            row=dict(clients=key[0],model=key[1],mode=key[2],runtime_sha256=key[3],job_ids=[i for i,_ in items],
                seeds=sorted(r['config']['seed'] for _,r in items),complete_three_seed_group=complete,statistics=None,learning_curve=[])
            if complete:
                stats=lambda values:dict(mean=statistics.mean(values),sample_SD=statistics.stdev(values))
                row['statistics']={metric:stats([r['final_test'][metric] for _,r in items]) for metric in ('accuracy','loss')}
                row['statistics']['recorded_job_seconds']=stats([r['recorded_job_seconds'] for _,r in items])
                rounds=[json.loads((pack/'results'/i/'metrics.json').read_text()) for i,_ in items]
                if all(len(records)==20 and all(records[index].get('validation') is not None and records[index]['round']==index+1 for index in (4,9,14,19)) for records in rounds):
                    for index in (4,9,14,19):
                        row['learning_curve'].append(dict(round=index+1,validation_accuracy=stats([records[index]['validation']['accuracy'] for records in rounds])))
            comparisons.append(row)
        scaling=dict(completed_cases=sum(i in receipts for i in ids),required_cases=36,
            complete_scaling=len(comparisons)==12 and all(r['complete_three_seed_group'] for r in comparisons),groups=comparisons,
            setting=spec,interpretation='Fixed total training set; more logical clients reduce samples/client and alter Dirichlet partitions. Single-GPU simulator, not distributed hardware scaling. Timings exclude paused downtime; runtime/source/data are held separate. Only complete three-seed groups receive mean/sample SD.')
        atomic(pack/'scaling_summary.json',scaling);value['scaling']=scaling
    atomic(pack/'summary.json',value);return value
