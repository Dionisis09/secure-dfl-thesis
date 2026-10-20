"""Validate the complete extension and export three-seed evidence for slides/dashboard."""
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/campaign_20261020_full'
KEYS=['campaign','dataset','split_type','dirichlet_alpha','dirichlet_min_samples','shards_per_client',
      'topology','caveman_cliques','barabasi_m','num_clients','security_mode','he_ratio',
      'execution_profile','timing_environment']
MEASURES={'accuracy':'final_accuracy_percent','loss':'final_test_loss',
          'communication':'communication_mib_per_round','round_seconds':'avg_round_time_seconds',
          'he_seconds':'avg_he_total_time_seconds'}


def md(frame):
    return '\n'.join(['| '+' | '.join(frame.columns)+' |','| '+' | '.join(['---']*len(frame.columns))+' |',
        *['| '+' | '.join('—' if pd.isna(v) else f'{v:.3f}' if isinstance(v,(float,np.floating)) else str(v) for v in row)+' |'
          for row in frame.itertuples(index=False,name=None)]])


def main():
    data=pd.read_csv(OUT/'summary.csv')
    assert len(data)==1440 and data.id.nunique()==1440
    if not data.status.eq('completed').all():raise ValueError('Final statistics require all 1,440 jobs completed')
    groups=[];curves=[];partitions={}
    for row in data.itertuples():
        path=ROOT/row.metrics_path
        frame=pd.read_csv(path)
        assert frame['round'].tolist()==list(range(1,21))
        assert np.isfinite(frame[['avg_test_accuracy','avg_test_loss','avg_train_loss']]).all().all()
        assert frame.avg_test_accuracy.between(0,100).all()
        meta=json.loads((OUT/'metadata'/f'{row.id}_metadata.json').read_text())
        assert meta['partition_complete']
        assert meta['seed']==row.seed and meta['dataset']==row.dataset and meta['num_clients']==row.num_clients
        assert meta['split_type']==row.split_type and meta['topology']==row.topology
        assert meta['timing_environment']==row.timing_environment
        expected=50000 if row.dataset=='cifar10' else 60000
        assert sum(c['samples'] for c in meta['partition_clients'])==expected
        alpha=None if pd.isna(row.dirichlet_alpha) else row.dirichlet_alpha
        pk=(row.dataset,row.split_type,alpha,row.num_clients,row.seed)
        hashes=tuple(c['indices_sha256'] for c in meta['partition_clients'])
        if pk in partitions:assert partitions[pk]==hashes
        else:partitions[pk]=hashes
        for raw in frame.to_dict('records'):
            curves.append({**{k:getattr(row,k) for k in KEYS},'seed':row.seed,'round':raw['round'],
                           'accuracy':raw['avg_test_accuracy']})
    for keys,frame in data.groupby(KEYS,dropna=False,sort=False):
        assert len(frame)==3 and sorted(frame.seed.tolist())==[1,2,3]
        r=dict(zip(KEYS,keys));r['n']=3
        for name,column in MEASURES.items():
            values=frame[column].astype(float)
            assert np.isfinite(values).all()
            r[name+'_mean']=float(values.mean());r[name+'_sd']=float(values.std(ddof=1))
        groups.append(r)
    grouped=pd.DataFrame(groups)
    assert len(grouped)==480
    grouped.to_csv(OUT/'grouped_summary.csv',index=False)
    curve=pd.DataFrame(curves).groupby([*KEYS,'round'],dropna=False).accuracy.agg(['mean','std','count']).reset_index()
    assert curve['count'].eq(3).all() and len(curve)==9600
    curve.to_csv(OUT/'grouped_learning_curves.csv',index=False)
    match=[k for k in KEYS if k not in ['security_mode','he_ratio']]+['seed']
    baseline=data[data.security_mode=='none']
    pairs=data[data.security_mode!='none'].merge(baseline[match+['id','final_accuracy_percent']],on=match,suffixes=('','_baseline'),validate='many_to_one')
    assert len(pairs)==1152
    pairs['accuracy_delta_pp']=pairs.final_accuracy_percent-pairs.final_accuracy_percent_baseline
    pairs[['id','id_baseline','dataset','split_type','dirichlet_alpha','topology','num_clients','seed','security_mode','accuracy_delta_pp']].to_csv(OUT/'accuracy_pairs.csv',index=False)
    he=data[data.security_mode=='adaptive_hybrid'].merge(
        data[data.security_mode=='selective_he'][match+['id','avg_he_total_time_seconds','communication_mib_per_round']],
        on=match,suffixes=('','_selective'),validate='one_to_one')
    assert len(he)==288 and he.avg_he_total_time_seconds_selective.gt(0).all()
    he['he_saved_percent']=100*(1-he.avg_he_total_time_seconds/he.avg_he_total_time_seconds_selective)
    he['communication_saved_percent']=100*(1-he.communication_mib_per_round/he.communication_mib_per_round_selective)
    he.to_csv(OUT/'he_pairs.csv',index=False)
    sources={'summary':str((OUT/'summary.csv').relative_to(ROOT)),
             'grouped':str((OUT/'grouped_summary.csv').relative_to(ROOT)),
             'curves':str((OUT/'grouped_learning_curves.csv').relative_to(ROOT))}
    evidence={'completed':1440,'group_count':480,'seeds':[1,2,3],
              'groups':json.loads(grouped.to_json(orient='records')),
              'curves':json.loads(curve.to_json(orient='records')),
              'accuracy_pairs':json.loads(pairs.to_json(orient='records')),
              'he_pairs':json.loads(he.to_json(orient='records')),'sources':sources}
    (OUT/'presentation_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    baseline=grouped[(grouped.security_mode=='none')&(grouped.split_type=='dirichlet')].copy()
    baseline['accuracy_mean_sd']=baseline.apply(lambda r:f'{r.accuracy_mean:.2f} ± {r.accuracy_sd:.2f}',axis=1)
    table=baseline[['dataset','num_clients','dirichlet_alpha','topology','accuracy_mean_sd']]
    note=f'''# Full Dirichlet and topology extension

1,440/1,440 completed runs, separate from the original 402-run campaign and
the eight exploratory diagnostics. Three seeds (1, 2, 3) per configuration,
three full datasets, 5/10 clients, five security modes, 20 rounds, batch 32,
one local epoch, SGD 0.01, and the same MLP with 128 hidden units.

1,080 runs cover Dirichlet alpha 0.1/0.5/1.0 on ring, fully connected,
Caveman and Barabasi-Albert. Another 360 cover IID and two-shard non-IID
on the two new topologies. Caveman has two balanced communities;
Barabasi-Albert has m=2. Dirichlet also changes client sample counts.

All 480 statistical groups have n=3. SD is sample SD (ddof=1), in percentage
points for accuracy. The accuracy is mean client accuracy on the full global
test split, after neighbor aggregation. Every partition covers all examples
once, and matching partitions across modes/topologies have identical index
hashes. The 1,152 protected/baseline pairs and 288 adaptive/selective pairs
match all partition, seed, topology and runtime configuration fields.

Timings belong to cached_gpu / parallel_2_workers and are kept separate
from the serial original profiles. They describe observed throughput under
concurrency, not isolated per-experiment latency. Accuracy preservation is
not a privacy guarantee. No CNN or preprocessing change was introduced.

## Baseline Dirichlet accuracy (mean ± sample SD, n=3)

{md(table)}

## Reproduction

```powershell
python src/run_extended_campaign.py --workers 2 --publish_dashboard
python src/summarize_extended_campaign.py
python src/publish_extended_campaign.py
```

The controller resumes complete metrics and metadata, retries failures up to
three times, and keeps its manifest/progress atomic. `grouped_summary.csv`,
`grouped_learning_curves.csv`, `accuracy_pairs.csv`, `he_pairs.csv` and
`presentation_evidence.json` preserve calculations and source identities.
'''
    (OUT/'README.md').write_text(note,encoding='utf-8')
    print('Validated 1,440 runs, 480 three-seed groups, 1,152 accuracy pairs and 288 HE pairs.')


if __name__=='__main__':main()
