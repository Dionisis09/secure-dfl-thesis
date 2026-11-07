"""Explicit simulator commands; prepare/status/plan never start training."""
import argparse,json,os,sys,time
from pathlib import Path
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8');os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    for name in ['prepare','status','plan','summarize','preflight']:
        q=s.add_parser(name);q.add_argument('--pack',required=True)
        if name=='prepare':q.add_argument('--scaling4090',action='store_true');q.add_argument('--clock-from')
    q=s.add_parser('prepare-data');q.add_argument('--pack',required=True);q.add_argument('--cache',required=True);q.add_argument('--official-data',default='data')
    q=s.add_parser('calibrate');q.add_argument('--pack',required=True);q.add_argument('--cache',required=True);q.add_argument('--topologies',default='ring')
    q=s.add_parser('run');q.add_argument('--pack',required=True);q.add_argument('--cache',required=True)
    q=s.add_parser('_job');q.add_argument('--config',required=True);q.add_argument('--output',required=True);q.add_argument('--cache',required=True);q.add_argument('--device',choices=['cuda','cpu'],default='cuda');q.add_argument('--deadline',type=float)
    a=p.parse_args()
    from simulator_pack.design import prepare,atomic,source_snapshot,digest,TOPOLOGIES
    if a.command=='prepare':
        m=prepare(a.pack,scaling4090=a.scaling4090,clock_from=a.clock_from);print(json.dumps(dict(status='prepared_not_started',candidate_jobs=m['candidate_jobs'],bundles=len(m['bundles']),clients=m['clients'],seeds=[1,2,3])))
    elif a.command=='status':print((Path(a.pack)/'state.json').read_text())
    elif a.command=='prepare-data':
        from simulator_pack.data import prepare as data
        values={n:data(a.cache,n,a.official_data) for n in ['mnist','fashion_mnist','cifar10']};snapshot=dict(datasets=values,sha256=digest(values));target=Path(a.pack)/'data_snapshot.json'
        if target.exists() and json.loads(target.read_text())!=snapshot:raise RuntimeError('frozen data differs; use a new pack')
        atomic(target,snapshot);print('All three official train/validation/test caches verified.')
    elif a.command=='preflight':
        import torch
        from simulator_pack.engine import runtime
        from simulator_pack.campaign import require_target,check_source
        from simulator_pack.protection import context
        if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable; no CPU fallback')
        check_source(a.pack);require_target(json.loads((Path(a.pack)/'manifest.json').read_text()),runtime('cuda'))
        x=torch.ones(16,16,device='cuda');x@x;torch.cuda.synchronize()
        c=context(dict(poly_modulus_degree=8192,coeff_mod_bit_sizes=[60,40,40,60],scale_bits=40,threads=1))
        import tenseal as ts
        value=(ts.ckks_vector(c.public_context,[.25,.5])+ts.ckks_vector(c.public_context,[.5,.25])).decrypt(c.secret_key)
        if max(abs(v-.75) for v in value)>1e-5:raise RuntimeError('CKKS preflight failed')
        result=dict(status='passed_no_training',runtime=runtime('cuda'),source=source_snapshot()['hash'],cuda_memory=torch.cuda.get_device_properties(0).total_memory,CKKS_encryption_addition_decryption=True)
        atomic(Path(a.pack)/'preflight.json',result);print(json.dumps(result))
    elif a.command=='_job':
        from simulator_pack.engine import execute
        from simulator_pack.campaign import lock
        with lock(Path(a.output)/'job.lock'):result=execute(a.output,json.loads(Path(a.config).read_text()),a.cache,device=a.device,deadline=a.deadline)
        print(json.dumps({k:v for k,v in result.items() if k not in ('config','runtime_profile')}))
    elif a.command=='summarize':
        from simulator_pack.report import summarize
        r=summarize(a.pack);print(json.dumps(dict(completed=r['verified_completed'],groups=len(r['groups']))))
    else:
        from simulator_pack.campaign import calibrate,plan,run
        if a.command=='plan':print(json.dumps(plan(a.pack)))
        elif a.command=='calibrate':
            topologies=tuple(a.topologies.split(','))
            if not set(topologies)<=set(TOPOLOGIES):raise ValueError('unsupported topology')
            calibrate(a.pack,a.cache,topologies)
        else:run(a.pack,a.cache)
if __name__=='__main__':main()
