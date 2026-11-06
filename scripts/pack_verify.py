"""Small integration fixtures, never campaign jobs or accuracy benchmarks.

The independent oracle is an explicitly trusted test operator outside the
coordinator. It does not form part of the deployed training protocol.
"""
import argparse,hashlib,json,os,re,shutil,sys
from pathlib import Path
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'src'))
import numpy as np
import torch
from experiment_pack.manifest import config
from experiment_pack.provision import provision
from experiment_pack.launch import launch
from experiment_pack.training import load,save,train,evaluate
from experiment_pack.protocol import local_counters
from experiment_pack.runtime import source_hash
from secure_protocol_v6.training_adapter import state_hash

def main():
    p=argparse.ArgumentParser();p.add_argument('--name',required=True);p.add_argument('--model',choices=['mlp','cnn'],required=True)
    p.add_argument('--data-cache',required=True);p.add_argument('--dataset',choices=['mnist','fashion_mnist','cifar10'],default='cifar10')
    p.add_argument('--topology',default='fully_connected');p.add_argument('--mode',default='hybrid_pairwise_head_he');p.add_argument('--clients',type=int,default=3)
    p.add_argument('--device',choices=['cpu','cuda'],default='cpu');p.add_argument('--rounds',type=int,default=1);p.add_argument('--preflight-only',action='store_true');a=p.parse_args()
    if not re.fullmatch('[a-z][a-z0-9_]{0,63}',a.name) or a.rounds not in (1,2):p.error('invalid fixture name/rounds')
    folder=root/'checks'/a.name;folder.mkdir(parents=True);data=folder/'data';data.mkdir()
    source=Path(a.data_cache)/a.dataset;metadata=json.loads((source/'receipt.json').read_text())
    for kind in ['train','validation','test']:
        with np.load(source/(kind+'.npz'),allow_pickle=False) as ds:
            n=a.clients*4 if kind=='train' else 6
            np.savez(data/(kind+'.npz'),images=ds['images'][:n],labels=ds['labels'][:n])
    metadata['sha256']={n:hashlib.sha256((data/n).read_bytes()).hexdigest() for n in ['train.npz','validation.npz','test.npz']}
    (data/'receipt.json').write_text(json.dumps(metadata))
    cfg=config(a.model,a.dataset,'iid',None,a.topology,a.mode,1,'smoke',lr=.001)
    cfg.update(test_fixture=True,clients=a.clients,rounds=a.rounds,batch_size=2,validation_every=1,training_device=a.device,sample_budget=None,evaluation_budget=None)
    workspace=provision(folder/'private',cfg,data);job=json.loads((workspace/'public_job.json').read_text())
    if a.preflight_only:
        result=launch(workspace,wall_limit_seconds=1200,preflight_only=True)
        assert result['no_training_performed'] and result['clients']==a.clients
        (folder/'audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(status='deployment_verified_no_training',clients=a.clients)));return
    oracle=folder/'trusted-test-auditor';oracle.mkdir();configs={}
    for name in job['roster']:
        target=oracle/name;target.mkdir()
        for file in ['checkpoint.pt','data.npz']:shutil.copyfile(workspace/name/file,target/file)
        private=json.loads((workspace/name/'config.json').read_text());private['private_dir']=str(target);configs[name]=private
    records=[];best_score=-1.;best={}
    for number in range(1,a.rounds+1):
        result=launch(workspace,max_new_rounds=1,wall_limit_seconds=1800)
        assert result['completed_rounds']==number
        states={};trained={}
        for name,private in configs.items():
            initial=load(Path(private['private_dir'])/'checkpoint.pt')
            trained[name]=train(private,dict(round=number,base=state_hash(initial['state'])))
            states[name]=trained[name]['state']
        hashes={};values=[];expected_models={}
        for name in job['roster']:
            peers=[name,*job['adjacency'][name]];expected={}
            for key,original in states[name].items():
                if original.is_floating_point():
                    total=sum(np.rint(states[n][key].numpy().astype(np.float64)*65536).astype(np.int64) for n in peers)
                    expected[key]=torch.tensor(total/(len(peers)*65536),dtype=original.dtype)
                else:expected[key]=torch.tensor(max(local_counters(job,number)[n] for n in peers),dtype=original.dtype)
            observed=load(workspace/name/'checkpoint.pt')['state']
            assert state_hash(expected)==state_hash(observed),(name,'quantized neighbor state mismatch')
            hashes[name]=state_hash(observed);expected_models[name]=expected
            values.append(evaluate(expected,str(workspace/'public-evaluation/validation.npz'),job))
            save(Path(configs[name]['private_dir'])/'checkpoint.pt',dict(round=number,state=expected,optimizer=trained[name]['optimizer'],rng=trained[name]['rng']))
        mean=np.sum(np.rint(np.asarray(values)*1e9).astype(np.int64),axis=0)/(len(values)*1e9)
        metrics=result['records'][number-1]['metrics']
        assert abs(metrics['validation_accuracy']-100*mean[0])<1e-7 and abs(metrics['validation_loss']-mean[1])<1e-9
        if mean[0]>best_score:best_score=mean[0];best=expected_models
        records.append(dict(round=number,neighbor_state_exact=True,metric_mean_exact=True,state_hashes=hashes))
    for name in job['roster']:
        assert state_hash(load(workspace/name/'best.pt')['state'])==state_hash(best[name])
    before=[hashlib.sha256((workspace/n/'checkpoint.pt').read_bytes()).hexdigest() for n in job['roster']]
    again=launch(workspace,wall_limit_seconds=1200)
    assert again['records']==result['records'] and before==[hashlib.sha256((workspace/n/'checkpoint.pt').read_bytes()).hexdigest() for n in job['roster']]
    receipt=dict(status='verified',model=a.model,dataset=a.dataset,topology=a.topology,mode=a.mode,clients=a.clients,rounds=a.rounds,
        device=a.device,records=records,complete_resume_does_not_train=True,private_best_checkpoint_exact=True,
        source_hash=source_hash(),all_services_stopped=True,scope='small correctness fixture; not a scientific campaign or accuracy benchmark')
    (folder/'audit.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({k:v for k,v in receipt.items() if k!='records'}))

if __name__=='__main__':main()
