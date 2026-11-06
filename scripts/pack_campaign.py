"""Build/status/preflight are non-training operations. Only explicit run launches."""
import argparse,json,os,sys
from pathlib import Path
def main():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--pack',required=True)
    s=sub.add_parser('status');s.add_argument('--pack',required=True)
    f=sub.add_parser('preflight');f.add_argument('--pack',required=True)
    a=sub.add_parser('summarize');a.add_argument('--pack',required=True)
    d=sub.add_parser('prepare-data');d.add_argument('--cache',required=True)
    z=sub.add_parser('freeze-data');z.add_argument('--pack',required=True);z.add_argument('--cache',required=True)
    e=sub.add_parser('run');e.add_argument('--pack',required=True);e.add_argument('--work-root',required=True);e.add_argument('--data-cache',required=True)
    e.add_argument('--until',choices=['gpu_gate','smoke','tuning','validation','sensitivity','network'],default='gpu_gate')
    e.add_argument('--max-estimated-hours',type=float,default=168);e.add_argument('--retain-private',action='store_true')
    args=p.parse_args()
    from experiment_pack.controller import build_pack,gpu_preflight,dump,execute
    if args.command=='build':
        m=build_pack(args.pack);print(json.dumps(dict(status='prepared_not_started',counts=m['counts'],unique_jobs=m['unique_jobs'],manifest_sha256=m['manifest_sha256'])))
    elif args.command=='status':print((Path(args.pack)/'state.json').read_text())
    elif args.command=='preflight':
        result=gpu_preflight();dump(Path(args.pack)/'preflight.json',result);print(json.dumps(result))
    elif args.command=='prepare-data':
        from experiment_pack.data import prepare
        for name in ('mnist','fashion_mnist','cifar10'):print(prepare(args.cache,name))
    elif args.command=='summarize':
        from experiment_pack.report import summarize
        value=summarize(args.pack);print(json.dumps(dict(pending=value['pending_jobs'],groups=len(value['groups']))))
    elif args.command=='freeze-data':
        from experiment_pack.controller import freeze_data
        value=freeze_data(args.pack,args.cache);print(json.dumps(dict(data_ready=True,sha256=value['sha256'])))
    else:print(json.dumps(execute(args.pack,args.work_root,args.data_cache,until=args.until,max_estimated_hours=args.max_estimated_hours,retain_private=args.retain_private)))
if __name__=='__main__':main()
