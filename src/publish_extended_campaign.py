"""Merge reviewed campaign checkpoints into the existing dashboard, preserving its ID."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/campaign_20261020_full'
DASH=Path(r'C:\Users\dioni\Documents\secure-dfl-results-dashboard')
NODE=Path(r'C:\Users\dioni\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe')
BUILD_TOOL=Path(r'C:\Users\dioni\.codex\plugins\cache\openai-curated-remote\data-analytics\1.1.0-exp-baseline\scripts\data-app.mjs')


def publish(build=True):
    path=DASH/'src/data.json'
    snapshot=json.loads(path.read_text(encoding='utf-8'))
    old=[r for r in snapshot['queries']['runs']['rows'] if r['id'].startswith('campaign_20261014_')]
    oldcurves=[r for r in snapshot['queries']['rounds']['rows'] if r['id'].startswith('campaign_20261014_')]
    assert len(old)==402 and all(r['status']=='completed' for r in old)
    for row in old+oldcurves:
        row.update(campaign='original_20261014',timing_environment='serial')
        row.update(comparison_scope='Original 402',execution_session='session_20261014')
        row['shards_per_client']=2 if row.get('split_type')=='non_iid' else None
    frame=pd.read_csv(OUT/'summary.csv')
    new=json.loads(frame.to_json(orient='records'))
    reduced_dir=ROOT/'results/campaign_20261102_reduced'
    reduced_path=reduced_dir/'scope.json'
    reduced=json.loads(reduced_path.read_text(encoding='utf-8')) if reduced_path.exists() else None
    reduced_ids=set(reduced['selected_ids']) if reduced else set()
    for row in new:
        row['comparison_scope']='Selected 228' if row['id'] in reduced_ids else 'Deferred extension'
        row['execution_session']=row.get('execution_session') or 'session_20261020'
    curves=[]
    fields=['campaign','workflow','dataset','security_mode','split_type','topology','num_clients','seed',
            'he_ratio','dirichlet_alpha','dirichlet_min_samples','shards_per_client','caveman_cliques','barabasi_m','execution_profile','timing_environment','comparison_scope','execution_session']
    for row in new:
        if row['status']!='completed':continue
        for r in pd.read_csv(ROOT/row['metrics_path']).to_dict('records'):
            curves.append({**{k:row.get(k) for k in fields},'id':row['id'],'round':int(r['round']),
                           'accuracy_percent':float(r['avg_test_accuracy'])})
    snapshot['queries']['runs']['rows']=old+new
    snapshot['queries']['rounds']['rows']=oldcurves+curves
    progress_path=OUT/'progress.json'
    progress=json.loads(progress_path.read_text()) if progress_path.exists() else dict(
        planned=len(new),**{s:sum(r['status']==s for r in new) for s in ['completed','running','pending','failed']},
        status='paused',updated_at=snapshot.get('generatedAt'))
    snapshot['campaign']={**progress,'planned':1842,'completed':402+progress['completed']}
    snapshot['generatedAt']=datetime.now(timezone.utc).isoformat()
    snapshot['buildStatus']='complete' if progress['completed']==1440 else 'updating'
    if reduced:
        scope_status_path=reduced_dir/'progress.json'
        if scope_status_path.exists():scope_progress=json.loads(scope_status_path.read_text(encoding='utf-8'))
        else:
            scoped=[r for r in new if r['id'] in reduced_ids]
            scope_progress=dict(planned=228,status='paused',**{s:sum(r['status']==s for r in scoped) for s in ['completed','running','pending','failed']})
        verified=(reduced_dir/'validation.json').exists()
        snapshot['queries']['reduced_scope']={'rows':[scope_progress],
            'source':dict(type='local',label='Explicitly selected reduced comparison series',
                files=['results/campaign_20261102_reduced/scope.json','results/campaign_20261020_full/summary.csv'],
                caveats=['228 is a subset of 1440, not an additional campaign. Alpha0.1/1 and IID/shards additions are baseline-only CIFAR10.'])}
        if scope_progress['status']=='paused':snapshot['buildStatus']='complete' if verified else 'paused'
    campaign=[]
    for workflow in ['validation','sensitivity','network']:
        n=sum(r['workflow']==workflow for r in old)
        campaign.append(dict(campaign='original_20261014',label='Original · '+workflow,workflow=workflow,
                             planned=n,completed=n,pending=0,running=0,failed=0))
    campaign.append(dict(campaign='extension_20261020',label='New · validation',workflow='validation',
                         **{k:progress[k] for k in ['planned','completed','pending','running','failed']}))
    snapshot['queries']['campaign']['rows']=campaign
    source=dict(type='local',label='Original campaign and full 3-seed extension',
        files=['results/campaign_20261014/summary.csv','results/campaign_20261020_full/summary.csv',
               'results/campaign_20261020_full/manifest.json'],
        metricDefinitions=[
            dict(label='Accuracy',definition='Mean client accuracy on the full held-out test set, after round 20. Group by campaign, dataset, split, Dirichlet alpha, topology parameters, clients and security mode. Sample SD uses n-1 across seeds and is undefined for n=1.'),
            dict(label='Timing strata',definition='Keep legacy and cached_gpu profiles separate. Also separate serial original runs from the new parallel_2_workers environment. Timing under concurrency is not an isolated latency benchmark.'),
            dict(label='New campaign',definition='1440 new validation runs: 1080 Dirichlet alpha 0.1/0.5/1.0 on ring/full/Caveman/Barabasi-Albert, plus 360 IID/shard runs on Caveman/Barabasi-Albert. Three datasets, 5/10 clients, 3 seeds and 5 security modes. Pending/failed jobs have no measured performance.'),
            dict(label='Partitions',definition='Shards: two per client. Dirichlet: per-class Dir(alpha) probabilities and multinomial counts, conditioned on at least 10 samples per client. It changes both label and quantity skew. Caveman: 2 balanced cliques; Barabasi-Albert m=2. Equal-neighbor aggregation remains unchanged.')],
        caveats=['Partial seed groups are shown with their actual n, never as finished three-seed estimates.',
                 'MLP 128, full datasets, 20 rounds, batch 32, SGD 0.01. No CNN or input normalization change.',
                 'Accuracy and HE reconstruction checks do not establish privacy equivalence.'])
    for query in ['runs','rounds']:
        snapshot['queries'][query]['source']=source
        if reduced:source['caveats']+=['The selected228 series contains180 core alpha0.5 runs plus48 baseline-only CIFAR10 additions. The remaining wider grid is deferred. Times are additionally separated by execution session.'] if query=='runs' else []
    snapshot['queries']['campaign']['source']=dict(type='local',label='Campaign coverage before filters',
        files=['results/campaign_20261020_full/progress.json','results/campaign_20261014/completion.json'])
    existing={f['id']:f for f in snapshot['filters']}
    defaults={'workflow':'validation','dataset':'all','split_type':'dirichlet','topology':'barabasi_albert',
              'num_clients':'5','security_mode':'all','execution_profile':'all'}
    filters=[dict(id='campaign',label='Campaign',field='campaign',defaultValue='extension_20261020',queryIds=['runs','rounds'])]
    if reduced:filters.append(dict(id='comparison_scope',label='Comparison scope',field='comparison_scope',defaultValue='Selected 228',queryIds=['runs','rounds']))
    for key in ['workflow','dataset','split_type','topology','num_clients','security_mode','execution_profile']:
        f=existing[key];f.update(defaultValue=defaults[key],queryIds=['runs','rounds']);filters.append(f)
    filters.insert(4,dict(id='dirichlet_alpha',label='Dirichlet alpha',field='dirichlet_alpha',defaultValue='all',queryIds=['runs','rounds']))
    snapshot['filters']=filters
    temp=path.with_name('data.json.tmp');temp.write_text(json.dumps(snapshot,ensure_ascii=False,separators=(',',':')),encoding='utf-8');os.replace(temp,path)
    if build:
        result=subprocess.run([str(NODE),str(BUILD_TOOL),'build','--project-dir',str(DASH),'--separate-data'],capture_output=True,text=True)
        (OUT/'dashboard-build.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError('Dashboard build failed; inspect dashboard-build.log')
    return progress


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--no-build',action='store_true');args=parser.parse_args()
    print(json.dumps(publish(not args.no_build),indent=2))
