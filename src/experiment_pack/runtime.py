"""Role bootstrap and immutable source identity; no automatic campaign start."""
import hashlib,json,os,sys
from pathlib import Path

def source_files():
    root=Path(__file__).resolve().parents[2]
    files=sorted((root/'src').rglob('*.py'))+sorted((root/'scripts').glob('pack_*.py'))
    files += [root/n for n in ['native/dfl_range/Cargo.toml','native/dfl_range/Cargo.lock','native/dfl_range/src/lib.rs','requirements-protocol-v8.txt']]
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest() for p in files}

def source_hash():
    from .manifest import digest
    return digest(source_files())

def replace_process(config,role):
    root=Path(__file__).resolve().parents[2];env=dict(os.environ)
    env['CUDA_VISIBLE_DEVICES']='0' if role=='gpu_worker' else ''
    argv=[sys.executable,'-u',str(root/'scripts/pack_role.py'),'--role',role,'--config',str(Path(config['private_dir'])/'config.json')]
    # GPU/runtime FDs must not survive exec and keep a prior CUDA context alive.
    # Do not close them under live driver threads: close-on-exec is atomic with
    # replacing the process. Standard streams remain the client's private log.
    for name in os.listdir('/proc/self/fd'):
        fd=int(name)
        if fd>2:
            try:os.set_inheritable(fd,False)
            except OSError:pass  # listdir's own descriptor is already closed
    os.execve(sys.executable,argv,env)

def role_main(args):
    from independent_clients.isolation import protect_memory,restrict_files
    protect_memory();path=Path(args.config).resolve();config=json.loads(path.read_text());private=Path(config['private_dir']).resolve()
    if private!=path.parent:raise RuntimeError('config outside private role directory')
    os.environ['TMPDIR']=str(private/'tmp');(private/'tmp').mkdir(exist_ok=True)
    os.environ['XDG_CACHE_HOME']=str(private/'cache');(private/'cache').mkdir(exist_ok=True)
    os.environ['CUDA_CACHE_PATH']=str(private/'cache'/'cuda');(private/'cache'/'cuda').mkdir(exist_ok=True)
    native=os.environ.get('DFL_RANGE_LIB')
    if not native:raise RuntimeError('native backend path required')
    is_client=args.role!='coordinator';root=Path(__file__).resolve().parents[2]
    extra=[native,*[root/n for n in ['native/dfl_range/Cargo.toml','native/dfl_range/Cargo.lock','native/dfl_range/src/lib.rs','requirements-protocol-v8.txt']]]
    if is_client:extra += [config['validation_path'],config['test_path']]
    profile=restrict_files(private,extra,gpu=is_client and config['job']['config']['training_device']=='cuda',
        connect_ports=[p['port'] for p in config['endpoints'].values()] if not is_client else (),
        bind_ports=[config['port']] if is_client else (),allow_python_exec=is_client)
    from independent_clients.common import run_lock
    if args.role=='coordinator':
        from .coordinator import run
        return run(config,profile,max_new_rounds=args.max_new_rounds,preflight_only=args.preflight_only)
    with run_lock(private/'service.lock'):
        if args.role=='gpu_worker':
            from .training import train
            request=json.loads((private/'round.json').read_text());train(config,request)
            replace_process(config,'client')
        from .service import Service
        from independent_clients.network import serve
        service=Service(config,isolation=profile);serve(service,config)
