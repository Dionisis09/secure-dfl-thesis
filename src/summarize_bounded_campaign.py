"""Verify only the explicitly selected subset; never mark the 1440 grid complete."""
import json
import hashlib
import numpy as np
import pandas as pd
import run_extended_campaign as c
from run_bounded_campaign import SCOPE
from summarize_extended_campaign import KEYS,MEASURES

def main():
    scope=json.loads((SCOPE/'scope.json').read_text(encoding='utf-8'))
    selected_ids=scope['selected_ids']
    for path,sha in scope['protected_metrics_sha256'].items():
        assert hashlib.sha256((c.ROOT/path).read_bytes()).hexdigest()==sha
    source=pd.read_csv(c.OUT/'summary.csv')
    data=source[source.id.isin(selected_ids)].copy()
    assert len(data)==228 and data.id.nunique()==228
    if not data.status.eq('completed').all(): raise ValueError('Selected subset is still incomplete')
    partitions={};curves=[];sessions={}
    for row in data.itertuples():
        frame=pd.read_csv(c.ROOT/row.metrics_path)
        assert frame['round'].tolist()==list(range(1,21))
        assert np.isfinite(frame[['avg_test_accuracy','avg_test_loss','avg_train_loss']]).all().all()
        assert frame.avg_test_accuracy.between(0,100).all()
        m=json.loads((c.OUT/'metadata'/f'{row.id}_metadata.json').read_text())
        assert m['partition_complete'] and m['dataset']==row.dataset and m['seed']==row.seed
        assert m['num_clients']==row.num_clients and m['split_type']==row.split_type and m['topology']==row.topology
        assert m['timing_environment']==row.timing_environment
        assert sum(x['samples'] for x in m['partition_clients'])==(50000 if row.dataset=='cifar10' else 60000)
        alpha=None if pd.isna(row.dirichlet_alpha) else row.dirichlet_alpha
        key=(row.dataset,row.split_type,alpha,row.num_clients,row.seed)
        hashes=tuple(x['indices_sha256'] for x in m['partition_clients'])
        if key in partitions:assert partitions[key]==hashes
        else:partitions[key]=hashes
        sessions[row.id]=m.get('execution_session','session_20261020')
        for raw in frame.to_dict('records'):
            curves.append({**{k:getattr(row,k) for k in KEYS},'seed':row.seed,'round':raw['round'],'accuracy':raw['avg_test_accuracy']})
    data['execution_session']=data.id.map(sessions)
    groups=[]
    # Accuracy/loss/communication use complete seed trios. Timing also has a
    # separate session-specific export, with actual n when dates cross a trio.
    for keys,f in data.groupby(KEYS,dropna=False,sort=False):
        assert len(f)==3 and sorted(f.seed.tolist())==[1,2,3]
        r=dict(zip(KEYS,keys));r['n']=3
        for name,col in MEASURES.items():
            assert np.isfinite(f[col]).all()
            if name in ['round_seconds','he_seconds'] and f.execution_session.nunique()!=1:
                r[name+'_mean']=None;r[name+'_sd']=None
                continue
            r[name+'_mean']=float(f[col].mean());r[name+'_sd']=float(f[col].std(ddof=1))
        groups.append(r)
    grouped=pd.DataFrame(groups);assert len(grouped)==76
    grouped.to_csv(SCOPE/'grouped_summary.csv',index=False)
    data['execution_session']=data.id.map(sessions)
    data.to_csv(SCOPE/'summary.csv',index=False)
    timing=data.groupby([*KEYS,'execution_session'],dropna=False)[['avg_round_time_seconds','avg_he_total_time_seconds']].agg(['mean','std','count'])
    timing.to_csv(SCOPE/'timing_by_session.csv')
    curve=pd.DataFrame(curves).groupby([*KEYS,'round'],dropna=False).accuracy.agg(['mean','std','count']).reset_index()
    assert len(curve)==1520 and curve['count'].eq(3).all()
    curve.to_csv(SCOPE/'grouped_learning_curves.csv',index=False)
    match=[k for k in KEYS if k not in ['security_mode','he_ratio']]+['seed']
    baseline=data[data.security_mode=='none']
    pairs=data[data.security_mode!='none'].merge(baseline[match+['id','final_accuracy_percent']],on=match,suffixes=('','_baseline'),validate='many_to_one')
    assert len(pairs)==144
    pairs['accuracy_delta_pp']=pairs.final_accuracy_percent-pairs.final_accuracy_percent_baseline
    pairs.to_csv(SCOPE/'accuracy_pairs.csv',index=False)
    he_match=match+['execution_session']
    he=data[data.security_mode=='adaptive_hybrid'].merge(data[data.security_mode=='selective_he'][he_match+['id','avg_he_total_time_seconds']],on=he_match,suffixes=('','_selective'),validate='one_to_one')
    assert len(he)==35 and he.avg_he_total_time_seconds_selective.gt(0).all()
    he['he_saved_percent']=100*(1-he.avg_he_total_time_seconds/he.avg_he_total_time_seconds_selective)
    he.to_csv(SCOPE/'he_pairs.csv',index=False)
    evidence=dict(scope_completed=228,full_grid_planned=1440,full_grid_completed=int(source.status.eq('completed').sum()),
        original_campaign_completed=402,group_count=76,seeds=[1,2,3],sd='sample SD, ddof=1',
        groups=json.loads(grouped.to_json(orient='records')),curves=json.loads(curve.to_json(orient='records')),
        max_abs_protected_accuracy_delta_pp=float(pairs.accuracy_delta_pp.abs().max()),
        paired_he_saving_percent_mean=float(he.he_saved_percent.mean()),he_same_session_pairs=len(he),
        caveats=['Not the full 1440 grid. Alpha sensitivity and IID/shards additions are baseline-only CIFAR10.',
                 'All datasets stay full size, with 20 rounds, batch32, one local epoch, MLP128 and SGD .01.',
                 'Original402, earlier8 diagnostics and server microbenchmarks are separate.',
                 'Timings use parallel_2_workers and are exported separately by execution session.',
                 'Accuracy preservation and HE reconstruction do not establish privacy equivalence.'])
    c.atomic(SCOPE/'presentation_evidence.json',evidence)
    c.atomic(SCOPE/'validation.json',dict(validated_at=c.now(),scope_completed=True,completed=228,
        groups=76,all_n=3,rounds_per_run=20,protected_old_files_unchanged=True,accuracy_pairs=144,he_pairs=35,
        broader_grid_completed=False))
    table=grouped[(grouped.dataset=='cifar10')&(grouped.security_mode=='none')].copy()
    table['accuracy_mean_sample_sd']=table.apply(lambda r:f'{r.accuracy_mean:.2f} +/- {r.accuracy_sd:.2f}',axis=1)
    table=table[['num_clients','topology','split_type','dirichlet_alpha','accuracy_mean_sample_sd']]
    lines=['# Reduced comparison series (2026-11-02)','',
        '228/228 selected runs verified; 76 configurations with seeds 1/2/3. These are a subset of the 1440-run plan, not an additional duplicate campaign. 119 existing outputs were reused and 109 runs were added. The original 402 runs remain separate.',
        '', 'Coverage: 180 Dirichlet alpha0.5 runs across three datasets, 5/10 clients, Caveman/Barabasi-Albert and five security modes; 24 extra baseline CIFAR runs for alpha0.1/1.0; 24 baseline CIFAR IID/two-shard runs. Other comparisons remain deferred.',
        '', 'Full datasets, MLP128, 20 rounds, one local epoch, batch32 and SGD0.01 retained. SD is sample SD (n-1), n=3. Times are observed under two-worker concurrency and have a separate session export.',
        '', '## CIFAR baseline accuracy (percent; mean +/- sample SD)', '',
        '| '+' | '.join(table.columns)+' |','| '+' | '.join(['---']*len(table.columns))+' |']
    lines.extend('| '+' | '.join('n/a' if pd.isna(v) else str(v) for v in row)+' |' for row in table.itertuples(index=False,name=None))
    lines+=['',f'Max absolute protected-vs-baseline accuracy difference across 144 matched pairs: {evidence["max_abs_protected_accuracy_delta_pp"]:.4f} percentage points.',
            '', 'No full-grid or universal topology conclusion follows from this reduced scope. Three seeds offer limited precision. HE processing savings do not imply the same reduction in whole-training time or equivalent privacy.']
    (SCOPE/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in evidence.items() if k not in ['groups','curves']},indent=2))

if __name__=='__main__':main()
