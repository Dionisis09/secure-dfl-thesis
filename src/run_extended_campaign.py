"""Resumable 1,440-run Dirichlet/topology campaign with atomic progress snapshots."""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict
from datetime import datetime, timezone
import gc
import hashlib
import itertools
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import sys
import time
import traceback
import pandas as pd
from run_validation_experiments import ValidationExperiment, summarize_run

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/campaign_20261020_full'
MODES = ['none','masking','pairwise_masking','selective_he','adaptive_hybrid']
DATASETS = ['mnist','fashion_mnist','cifar10']


def now():return datetime.now(timezone.utc).isoformat()


def atomic(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    os.replace(temp,path)


def make_plan():
    jobs=[]
    for seed,dataset,clients,mode in itertools.product([1,2,3],DATASETS,[5,10],MODES):
        variants=[('dirichlet',t,a) for a in [0.1,0.5,1.0]
                  for t in ['ring','fully_connected','caveman','barabasi_albert']]
        variants += [(s,t,0.5) for s in ['iid','non_iid'] for t in ['caveman','barabasi_albert']]
        for split,topology,alpha in variants:
            exp=ValidationExperiment(seed,dataset,clients,topology,split,mode,20,32,'topk_risk',0.4,
                dirichlet_alpha=alpha,execution_profile='cached_gpu')
            name='campaign_20261020_full_'+exp.name
            jobs.append(dict(id=name,campaign='extension_20261020',workflow='validation',
                experiment=asdict(exp),dataset=dataset,seed=seed,num_clients=clients,
                topology=topology,split_type=split,security_mode=mode,num_rounds=20,
                batch_size=32,he_ratio=0.4 if mode=='adaptive_hybrid' else None,
                dirichlet_alpha=alpha if split=='dirichlet' else None,
                dirichlet_min_samples=10 if split=='dirichlet' else None,
                shards_per_client=2 if split=='non_iid' else None,
                caveman_cliques=2 if topology=='caveman' else None,
                barabasi_m=2 if topology=='barabasi_albert' else None,
                execution_profile='cached_gpu',status='pending',attempts=0,
                metrics_path=f'results/campaign_20261020_full/metrics/{name}_metrics.csv'))
    assert len(jobs)==1440 and len({j['id'] for j in jobs})==1440
    # Bring all seeds of each configuration together, and finish the basic
    # alpha=.5/new-topology comparison before the wider sensitivity grid.
    jobs.sort(key=lambda j:(0 if j['split_type']=='dirichlet' and j['dirichlet_alpha']==0.5 and j['topology'] in ['caveman','barabasi_albert'] else 1,
        j['dataset'],j['num_clients'],j['split_type'],j['dirichlet_alpha'] or 0,j['topology'],j['security_mode'],j['seed']))
    return jobs


def worker(task_queue, events, worker_id):
    os.environ['OMP_NUM_THREADS']='1';os.environ['MKL_NUM_THREADS']='1'
    import torch
    import main as training
    from config import Config
    torch.set_num_threads(1)
    cache={};get=training.get_datasets
    def cached(name, directory, cache_device=None):
        key=(name,directory,cache_device)
        if key not in cache:cache[key]=get(name,directory,cache_device=cache_device)
        return cache[key]
    training.get_datasets=cached
    while True:
        job=task_queue.get()
        if job is None:return
        events.put(dict(kind='started',id=job['id'],worker=worker_id,at=now()))
        start=time.monotonic()
        try:
            cfg=Config()
            args=argparse.Namespace(**vars(cfg))
            args.lr=cfg.learning_rate
            for key,value in job['experiment'].items():setattr(args,key,value)
            args.experiment_name=job['id'];args.device='cuda'
            args.enable_audit=False;args.enable_blockchain=False
            log=OUT/'execution_logs'/f"{job['id']}.log"
            with log.open('w',encoding='utf-8') as stream,redirect_stdout(stream),redirect_stderr(stream):
                result=training.run_experiment(args)
            # Concurrency is an explicit timing stratum, separate from the
            # original cached_gpu campaign; numeric training is unchanged.
            for row in result.metrics:row['timing_environment']=job['timing_environment']
            result.save_csv(str(ROOT/job['metrics_path']))
            meta=ROOT/'results/logs'/f"{job['id']}_metadata.json"
            metadata=json.loads(meta.read_text(encoding='utf-8'))
            metadata.update(timing_environment=job['timing_environment'],worker_id=worker_id,
                            immutable_image_cache_reused=True,campaign='extension_20261020')
            atomic(OUT/'metadata'/meta.name,metadata)
            events.put(dict(kind='completed',id=job['id'],worker=worker_id,at=now(),duration_seconds=time.monotonic()-start))
            del result
            gc.collect()
        except BaseException:
            events.put(dict(kind='failed',id=job['id'],worker=worker_id,at=now(),error=traceback.format_exc()))
            gc.collect()
            torch.cuda.empty_cache()


def valid(job):
    path=ROOT/job['metrics_path']
    if not path.exists() or not (OUT/'metadata'/f"{job['id']}_metadata.json").exists():return False
    try:summarize_run(path,ValidationExperiment(**job['experiment']));return True
    except (ValueError,KeyError,pd.errors.ParserError):return False


def publish(plan):
    records=[]
    for job in plan:
        row={k:v for k,v in job.items() if k!='experiment'}
        if job['status']=='completed':
            values=summarize_run(ROOT/job['metrics_path'],ValidationExperiment(**job['experiment']))
            values.pop('experiment_name',None);row.update(values)
        records.append(row)
    counts={s:sum(j['status']==s for j in plan) for s in ['completed','running','pending','failed']}
    durations=[j['duration_seconds'] for j in plan if j['status']=='completed' and 'duration_seconds' in j]
    progress=dict(planned=len(plan),**counts,updated_at=now())
    if durations:
        progress['observed_mean_run_seconds']=sum(durations)/len(durations)
        progress['eta_seconds']=sum(j['status'] in ['pending','running'] for j in plan)*progress['observed_mean_run_seconds']/plan[0]['worker_count']
    atomic(OUT/'manifest.json',plan)
    atomic(OUT/'progress.json',progress)
    frame=pd.DataFrame(records)
    tmp=OUT/'summary.csv.tmp';frame.to_csv(tmp,index=False);os.replace(tmp,OUT/'summary.csv')
    return progress


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,choices=[1,2,3],default=2)
    parser.add_argument('--dry_run',action='store_true')
    parser.add_argument('--max_jobs',type=int,default=None,help='Bounded pilot; production omits this option')
    parser.add_argument('--publish_dashboard',action='store_true',help='Refresh the existing dashboard every two minutes')
    args=parser.parse_args()
    plan=make_plan()
    if args.dry_run:
        print(json.dumps(dict(planned=len(plan),dirichlet=1080,new_topologies_iid_shards=360,
              workers=args.workers,first=plan[0],last=plan[-1]),indent=2));return
    OUT.mkdir(parents=True,exist_ok=True)
    lock=OUT/'controller.lock'
    if lock.exists():
        pid=int(lock.read_text())
        import ctypes
        handle=ctypes.windll.kernel32.OpenProcess(0x1000,False,pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            raise RuntimeError(f'Campaign controller {pid} is already running')
    for directory in ['execution_logs','metrics','metadata']:(OUT/directory).mkdir(exist_ok=True)
    prior={j['id']:j for j in json.loads((OUT/'manifest.json').read_text())} if (OUT/'manifest.json').exists() else {}
    for j in plan:
        if j['id'] in prior:
            old=prior[j['id']]
            if old['experiment']!=j['experiment']:raise ValueError('Saved experiment configuration changed')
            j.update(old)
        if j.get('worker_count',args.workers)!=args.workers:raise ValueError('Resume requires the same worker count/timing stratum')
        j['worker_count']=args.workers;j['timing_environment']=f'parallel_{args.workers}_workers'
        j['status']='completed' if valid(j) else ('failed' if j.get('attempts',0)>=3 else 'pending')
    publish(plan)
    lock.write_text(str(os.getpid()))
    atomic(OUT/'source_snapshot.json',{'captured_at':now(),'files':{
        p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src').glob('*.py')}})
    context=mp.get_context('spawn');tasks=context.Queue();events=context.Queue()
    workers=[context.Process(target=worker,args=(tasks,events,i)) for i in range(args.workers)]
    for w in workers:w.start()
    active={};started=0;done_since_publish=0;last_publish=time.monotonic();last_dashboard=0
    try:
        while True:
            pending=[j for j in plan if j['status']=='pending']
            while pending and len(active)<args.workers and (args.max_jobs is None or started<args.max_jobs):
                j=pending.pop(0);j['status']='running';j['attempts']+=1
                active[j['id']]=j;tasks.put(j);started+=1
            if not active:break
            try:event=events.get(timeout=10)
            except queue.Empty:
                if not all(w.is_alive() for w in workers):raise RuntimeError('A campaign worker exited; restart the resumable controller')
            else:
                j=active[event['id']]
                if event['kind']=='started':j['started_at']=event['at'];j['worker']=event['worker']
                else:
                    active.pop(j['id']);j['finished_at']=event['at']
                    if event['kind']=='completed' and valid(j):
                        j['status']='completed';j['duration_seconds']=event['duration_seconds'];j.pop('error',None)
                    else:
                        j['status']='pending' if j['attempts']<3 else 'failed';j['error']=event.get('error','Incomplete result')
                    done_since_publish+=1
                    print(f"{now()} {j['status']} {j['id']}",flush=True)
            if done_since_publish or time.monotonic()-last_publish>30:
                publish(plan);last_publish=time.monotonic();done_since_publish=0
                if args.publish_dashboard and time.monotonic()-last_dashboard>120:
                    try:
                        from publish_extended_campaign import publish as publish_dashboard
                        publish_dashboard()
                    except Exception:
                        atomic(OUT/'dashboard-error.json',dict(at=now(),error=traceback.format_exc()))
                    last_dashboard=time.monotonic()
        progress=publish(plan)
        if progress['completed']==len(plan):
            atomic(OUT/'completion.json',dict(finished_at=now(),completed=len(plan),failed=0))
        if args.publish_dashboard:
            from publish_extended_campaign import publish as publish_dashboard
            publish_dashboard()
    finally:
        for _ in workers:tasks.put(None)
        for w in workers:w.join(timeout=30)
        for w in workers:
            if w.is_alive():w.terminate()
        lock.unlink(missing_ok=True)


if __name__=='__main__':main()
