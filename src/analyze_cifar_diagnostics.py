"""Reconcile exploratory CIFAR runs with original evidence and write a concise guide."""
import json
from pathlib import Path
import numpy as np
import pandas as pd


def table(frame):
    def fmt(v):
        if pd.isna(v):return '—'
        if isinstance(v,(float,np.floating)):return f'{v:.3f}'
        return str(v)
    return '\n'.join(['| '+' | '.join(frame.columns)+' |',
                      '| '+' | '.join(['---']*len(frame.columns))+' |',
                      *['| '+' | '.join(fmt(v) for v in row)+' |' for row in frame.itertuples(index=False,name=None)]])


def main():
    root=Path(__file__).resolve().parents[1]
    out=root/'results/campaign_20261020_extension'
    summary=pd.read_csv(out/'summary.csv')
    if len(summary)!=len(json.loads((out/'plan.json').read_text())):
        raise ValueError('Exploratory plan is incomplete')
    old=pd.read_csv(root/'results/campaign_20261014/summary.csv')
    baseline=old[(old.workflow=='validation')&(old.dataset=='cifar10')&(old.security_mode=='none')]
    reference=baseline.groupby(['num_clients','topology','split_type']).final_accuracy_percent.agg(['mean','std','count']).reset_index()
    reference.to_csv(out/'original_cifar_baselines.csv',index=False)
    bycase=summary.set_index('case')
    diag={}
    integrity=[]
    for row in summary.itertuples():
        prefix=out/row.experiment_name
        metrics=pd.read_csv(str(prefix)+'_metrics.csv')
        meta=json.loads(Path(str(prefix)+'_metadata.json').read_text())
        details=json.loads(Path(str(prefix)+'_diagnostics.json').read_text())
        assert meta['partition_complete'] and sum(c['samples'] for c in meta['partition_clients'])==50000
        assert len(metrics)==row.num_rounds and metrics['round'].tolist()==list(range(1,row.num_rounds+1))
        acc=np.mean([c['global_test']['accuracy_percent'] for c in details['per_client']])
        assert abs(acc-row.final_accuracy)<1e-9
        for c in details['per_client']:
            assert sum(map(sum,c['global_test']['confusion_matrix_true_by_predicted']))==10000
        diag[row.case]={
            'mean_local_train_accuracy':float(np.mean([c['local_train']['accuracy_percent'] for c in details['per_client']])),
            'mean_global_test_accuracy':float(acc),
            'virtual_mean_model_test_accuracy':details['virtual_mean_model_test']['accuracy_percent'],
            'local_classes_present':[c['classes_present'] for c in meta['partition_clients']],
            'local_sample_counts':[c['samples'] for c in meta['partition_clients']],
            'partition_hashes':[c['indices_sha256'] for c in meta['partition_clients']],
            'degree_plus_self_stationary_weights':meta['fixed_graph_stationary_weights'],
        }
        if row.split_type in ['iid','non_iid'] and row.topology in ['ring','fully_connected']:
            match=baseline[(baseline.seed==row.seed)&(baseline.num_clients==5)&(baseline.split_type==row.split_type)&(baseline.topology==row.topology)].iloc[0]
            original=pd.read_csv(root/match.metrics_path)
            columns=['avg_test_accuracy','avg_test_loss','avg_train_loss']
            delta=float(np.max(np.abs(original[columns].to_numpy()-metrics.iloc[:20][columns].to_numpy())))
            assert delta<1e-9,(row.case,delta)
            integrity.append({'case':row.case,'reference':match.metrics_path,'max_abs_non_time_metric_difference_first20':delta})
    for case in ['dir05_caveman_20r','dir05_barabasi_20r']:
        assert diag[case]['partition_hashes']==diag['dir05_ring_20r']['partition_hashes']
    mode_data=old[(old.workflow=='validation')&(old.dataset=='cifar10')]
    pairs=mode_data.merge(baseline[['seed','num_clients','topology','split_type','final_accuracy_percent']],
        on=['seed','num_clients','topology','split_type'],suffixes=('','_baseline'))
    pairs=pairs[pairs.security_mode!='none'].copy()
    pairs['delta_accuracy_pp']=pairs.final_accuracy_percent-pairs.final_accuracy_percent_baseline
    pairs[['id','delta_accuracy_pp']].to_csv(out/'original_cifar_security_differences.csv',index=False)
    max_delta=float(pairs.delta_accuracy_pp.abs().max())
    (out/'verification.json').write_text(json.dumps({'completed':len(summary),'independent_confusion_matrix_reconciliation':'pass',
        'original_curve_reproductions':integrity,'same_dir05_partition_across_new_topologies':True,
        'original_cifar_matched_security_pairs':len(pairs),'max_absolute_security_delta_pp':max_delta,
        'diagnostics':diag},indent=2))
    summary['effective_alpha']=summary.dirichlet_alpha.where(summary.split_type=='dirichlet')
    display=summary[['case','effective_alpha','num_rounds','accuracy_round20','final_accuracy']].copy()
    display.columns=['Experiment (seed 1)','Dirichlet alpha','Rounds','Accuracy at 20 (%)','Final accuracy (%)']
    shards=bycase.loc['shards_ring_40r'];iid=bycase.loc['iid_ring_40r']
    text=f'''# CIFAR-10 accuracy investigation and new experiment options

The low non-IID accuracy is reproducible with the existing MLP and shard split.
The investigation did not find a CIFAR loading, caching or accuracy-denominator
error in the checks performed. Increasing the round budget from 20 to 40
improves shard/ring accuracy only from {shards.accuracy_round20:.2f}% to
{shards.final_accuracy:.2f}% for seed 1. IID reaches {iid.final_accuracy:.2f}%
at 40 rounds with the same MLP. The evidence supports a substantial difficulty
from the partition and decentralized training setup. The contribution of the
MLP architecture itself has not been isolated with a CNN ablation.

## Scope and metric

Eight exploratory runs, one seed (1), full CIFAR-10 (50,000 train and 10,000
test), 5 clients, batch 32, SGD 0.01, one local epoch per round, SimpleMLP
(Flatten, Linear(3072,128), ReLU, Linear(128,10)), cached GPU execution.
Accuracy is the equal mean of the five clients' accuracies on the full shared
test set after synchronous neighbor aggregation. It is not accuracy on a
client's restricted training labels and not virtual mean-model accuracy.
The two 40-round runs use their round-20 checkpoints for equal-budget
comparisons. All other runs have 20 rounds. These are controlled exploratory
comparisons with no confidence interval or seed SD.

## New measurements

{table(display)}

## Original multi-seed context

The original 402-run campaign remains separate and unchanged. Its CIFAR-10
baseline uses 3 seeds per configuration, with sample SD in percentage points:

{table(reference)}

Across {len(pairs)} matched original CIFAR-10 security-versus-baseline pairs,
the maximum absolute accuracy change is {max_delta:.3f} pp. The large
IID/non-IID gap is therefore also present without encryption and masking.

## What the checks establish

- The first 20 rounds of the new IID/ring, shards/ring and shards/full runs
  reproduce original seed-1 accuracy, training loss and test loss within
  1e-9. See `verification.json` for measured deltas and original source paths.
- The original shard split gives each of the five CIFAR clients exactly
  two classes and 10,000 training examples. Evaluation still covers all ten
  classes. At round 40, mean local training accuracy is
  {diag['shards_ring_40r']['mean_local_train_accuracy']:.2f}%, while mean
  global-test accuracy is {diag['shards_ring_40r']['mean_global_test_accuracy']:.2f}%.
  Local fitting does not establish generalization to all classes.
- Switching only ring to full connectivity improves the shard result at
  round 20 from {shards.accuracy_round20:.2f}% to
  {bycase.loc['shards_full_20r'].final_accuracy:.2f}% for the same seed and
  partition, while doubling directed model transmissions (10 to 20).
- Every new partition covers all 50,000 samples exactly once. For Dirichlet
  alpha 0.5 the three topology runs have identical per-client index hashes.
- Independent final confusion matrices reconcile the logged mean accuracy.
  Each client sees exactly 10,000 test examples. Existing regression tests
  check RGB tensor values/channel order against uncached ToTensor data.
- Real CPU/CKKS integration checks cover all five security modes with both
  new topologies on a small synthetic RGB dataset. Separate local HTTP smoke
  demos with synthetic data passed for Caveman and Barabasi-Albert. Those
  functional checks are not CIFAR accuracy evidence.

## Interpretation and limits

Severe class concentration, local updates before mixing, and limited graph
mixing are consistent with the observed gap. More rounds alone do not remove
it in this test. SimpleMLP flattens RGB images and has no convolutional spatial
features. A separate CNN comparison is needed to quantify that architectural
limitation; changing the original model would create a different experiment.

Dirichlet changes both labels and client sample counts. In this implementation
each class draws Dir(alpha) client probabilities, then multinomial counts,
without replacement. The complete draw repeats until every client has at
least 10 samples, with an explicit failure after 1,000 failed attempts.
The new allocation is not an equal-size shard split. Do not select an alpha
because it happens to yield the highest test accuracy in one seed.

Caveman uses two balanced communities (sizes 3 and 2 here), with the
connectivity-preserving size-two extension documented in the main README.
Barabasi-Albert uses m=2. With only five nodes these are small graph instances,
not evidence of scale-free behavior. The unchanged equal-neighbor aggregation
has stationary mixing weights proportional to degree+1 on undirected graphs.
Irregular degrees and Dirichlet quantity skew must therefore be considered
before attributing differences solely to topology. No sample-weighted or
Metropolis mixing was introduced.

The eight runs are exploratory, not a replacement for a matched three-seed
validation over all security modes. New results are deliberately separate
from the existing PowerPoint, thesis and dashboard's 402-run claims.

## Reproduction and evidence

```powershell
python src/run_cifar_diagnostics.py --dry_run
python src/run_cifar_diagnostics.py --output_dir results/cifar_reproduction
python src/run_cifar_diagnostics.py --resume
python src/analyze_cifar_diagnostics.py
python -m unittest discover -s tests -v
```

`plan.json` defines the eight configurations. `summary.csv` contains measured
run results, `*_metrics.csv` the round curves, `*_metadata.json` the partitions
and graph, and `*_diagnostics.json` the client confusion matrices.
`verification.json` records reconciliations and per-client local/global
accuracy. Original references come from `../campaign_20261014/summary.csv`
and its `metrics_path` records. Code entry points are
`src/main.py`, `src/data_utils.py`, `src/topology.py`, `src/client.py` and
`src/experiment_diagnostics.py`.

Method definitions: [connected Caveman](https://networkx.org/documentation/stable/reference/generated/networkx.generators.community.connected_caveman_graph.html),
[Barabasi-Albert](https://networkx.org/documentation/stable/reference/generated/networkx.generators.random_graphs.barabasi_albert_graph.html),
[Dirichlet partitions](https://flower.ai/docs/datasets/ref-api/flwr_datasets.partitioner.DirichletPartitioner.html).
'''
    (out/'README.md').write_text(text,encoding='utf-8')
    print('Reconciled 8 runs, original seed-1 curves, confusion matrices and matched topology partitions.')


if __name__=='__main__':main()
