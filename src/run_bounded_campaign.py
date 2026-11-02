"""Resume a declared 228-run subset with an independent wall-clock cutoff."""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import queue
import subprocess
import sys
import time
import os
import run_extended_campaign as c

SCOPE=c.ROOT/'results/campaign_20261102_reduced'
SESSION='session_20261102_bounded'

def selected(job):
    if job['topology'] not in ['caveman','barabasi_albert']: return False
    core=job['split_type']=='dirichlet' and job['dirichlet_alpha']==.5
    extra=job['dataset']=='cifar10' and job['security_mode']=='none' and (
        job['split_type'] in ['iid','non_iid'] or
        (job['split_type']=='dirichlet' and job['dirichlet_alpha'] in [.1,1.]))
    return core or extra

def remaining_seconds(deadline):
    return (deadline-datetime.now(timezone.utc)).total_seconds()

def process_alive(pid):
    k=ctypes.windll.kernel32
    k.OpenProcess.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.c_uint]
    k.OpenProcess.restype=ctypes.c_void_p
    k.CloseHandle.argtypes=[ctypes.c_void_p]
    h=k.OpenProcess(0x1000,False,pid)
    if not h: return False
    k.CloseHandle(h); return True

def write_progress(plan,deadline,state):
    p=c.publish(plan)
    p.update(status=state,deadline_utc=deadline.isoformat(),execution_session=SESSION)
    if state!='running': p['eta_seconds']=None
    c.atomic(c.OUT/'progress.json',p)
    jobs=[j for j in plan if selected(j)]
    counts={s:sum(j['status']==s for j in jobs) for s in ['completed','running','pending','failed']}
    c.atomic(SCOPE/'progress.json',dict(planned=228,**counts,status=state,
        updated_at=c.now(),deadline_utc=deadline.isoformat(),remaining_seconds=max(0,remaining_seconds(deadline)),
        full_campaign_completed=p['completed'],full_campaign_planned=1440))
    return counts

def recover(deadline,reason):
    plan=json.loads((c.OUT/'manifest.json').read_text(encoding='utf-8'))
    for job in plan:
        if job['status']=='running':
            job['status']='completed' if c.valid(job) else 'pending'
            if job['status']=='pending': job['attempts']=max(0,job.get('attempts',1)-1)
    counts=write_progress(plan,deadline,'paused')
    c.atomic(c.OUT/'pause.json',dict(status='paused',paused_at=c.now(),reason=reason,
        resume_only_on_user_request=True,execution_session=SESSION))
    (c.OUT/'controller.lock').unlink(missing_ok=True)
    c.atomic(SCOPE/'stopped.json',dict(at=c.now(),reason=reason,**counts))

def watchdog(pid,deadline):
    while process_alive(pid):
        if remaining_seconds(deadline)<=0:
            c.atomic(SCOPE/'hard_deadline.json',dict(at=c.now(),controller_pid=pid))
            subprocess.run(['taskkill.exe','/PID',str(pid),'/T','/F'],capture_output=True)
            recover(deadline,'User one-hour deadline reached; completed outputs preserved')
            return
        time.sleep(min(1,max(.05,remaining_seconds(deadline))))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--deadline-utc',required=True)
    p.add_argument('--watchdog-for',type=int)
    args=p.parse_args()
    deadline=datetime.fromisoformat(args.deadline_utc)
    if deadline.tzinfo is None: raise ValueError('Deadline needs timezone')
    if args.watchdog_for:
        watchdog(args.watchdog_for,deadline); return
    if remaining_seconds(deadline)<=180: raise ValueError('Too little time to start safely')
    lock=c.OUT/'controller.lock'
    if lock.exists() and process_alive(int(lock.read_text())): raise RuntimeError('A controller already runs')
    plan=json.loads((c.OUT/'manifest.json').read_text(encoding='utf-8'))
    assert len(plan)==1440 and sum(selected(j) for j in plan)==228
    protected={}
    for j in plan:
        if j.get('worker_count')!=2: raise ValueError('Keep the original two-worker timing stratum')
        if j['status']=='completed':
            assert c.valid(j),j['id']
            protected[j['metrics_path']]=hashlib.sha256((c.ROOT/j['metrics_path']).read_bytes()).hexdigest()
    SCOPE.mkdir(parents=True,exist_ok=True)
    if (SCOPE/'scope.json').exists(): raise RuntimeError('Bounded session already exists; inspect before rerunning')
    c.atomic(SCOPE/'scope.json',dict(planned=228,seeds=[1,2,3],started_at=c.now(),
        deadline_utc=deadline.isoformat(),execution_session=SESSION,selected_ids=[j['id'] for j in plan if selected(j)],
        initial_completed=len(protected),protected_metrics_sha256=protected,
        methodology='Full datasets, MLP128, 20 rounds, batch32, local epoch1, SGD .01; no hyperparameter reductions',
        coverage='180 core alpha.5 runs, all datasets/clients/modes; 48 extra CIFAR baseline runs for alpha.1/1 and IID/shards on new topologies'))
    lock.write_text(str(os.getpid()))
    c.atomic(SCOPE/'source_snapshot.json',{str(f.relative_to(c.ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (c.ROOT/'src').glob('*.py')})
    # A separate process kills the complete controller tree even if a worker or
    # publisher blocks. It is not a scheduled automation and cannot resume work.
    wdlog=(SCOPE/'watchdog.log').open('a',encoding='utf-8')
    subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--deadline-utc',deadline.isoformat(),
                      '--watchdog-for',str(os.getpid())],stdout=wdlog,stderr=wdlog)
    context=mp.get_context('spawn'); tasks=context.Queue(); events=context.Queue()
    workers=[context.Process(target=c.worker,args=(tasks,events,i)) for i in range(2)]
    for w in workers: w.start()
    active={}; last=0; reason='Selected scope completed'
    try:
        write_progress(plan,deadline,'running')
        while True:
            pending=[j for j in plan if selected(j) and j['status']=='pending']
            # Leave 150 seconds to finish the currently active runs and save.
            while pending and len(active)<2 and remaining_seconds(deadline)>150:
                j=pending.pop(0);j['status']='running';j['attempts']+=1
                j['execution_session']=SESSION
                active[j['id']]=j;tasks.put(j)
            if not active:
                if pending: reason='Admission cutoff reached before one-hour deadline'
                break
            if remaining_seconds(deadline)<=8:
                reason='Deadline safety stop';break
            try: e=events.get(timeout=min(3,max(.1,remaining_seconds(deadline)-7)))
            except queue.Empty:
                if not all(w.is_alive() for w in workers): raise RuntimeError('Worker exited')
            else:
                j=active[e['id']]
                if e['kind']=='started':j['started_at']=e['at'];j['worker']=e['worker']
                else:
                    active.pop(j['id']);j['finished_at']=e['at']
                    if e['kind']=='completed' and c.valid(j):
                        j['status']='completed';j['duration_seconds']=e['duration_seconds'];j.pop('error',None)
                        meta=c.OUT/'metadata'/f"{j['id']}_metadata.json"
                        m=json.loads(meta.read_text());m['execution_session']=SESSION;c.atomic(meta,m)
                    else:
                        j['status']='pending' if j['attempts']<3 else 'failed';j['error']=e.get('error','Incomplete result')
                    print(c.now(),j['status'],j['id'],flush=True)
                    last=0
            if time.monotonic()-last>15:
                write_progress(plan,deadline,'running');last=time.monotonic()
    finally:
        for w in workers:
            if w.is_alive(): w.terminate()
        for w in workers: w.join(timeout=1)
        for j in active.values():
            j['status']='completed' if c.valid(j) else 'pending'
            if j['status']=='pending':j['attempts']=max(0,j['attempts']-1)
        counts=write_progress(plan,deadline,'paused')
        for path,sha in protected.items():assert hashlib.sha256((c.ROOT/path).read_bytes()).hexdigest()==sha
        complete=counts['completed']==228
        c.atomic(SCOPE/'stopped.json',dict(at=c.now(),reason=reason,scope_completed=complete,**counts))
        c.atomic(c.OUT/'pause.json',dict(status='paused',paused_at=c.now(),reason='Bounded subset session ended; wider campaign remains deferred',resume_only_on_user_request=True))
        lock.unlink(missing_ok=True)
        print(json.dumps(dict(scope_completed=complete,**counts)),flush=True)

if __name__=='__main__':main()
