"""A separate 24-hour laptop campaign; the frozen server engine stays unchanged."""
import datetime
import hashlib
import itertools
import json
import statistics
import subprocess
import time
from pathlib import Path

from simulator_pack.design import atomic, configuration, digest, source_snapshot as engine_source
from simulator_pack.campaign import check_data, child, lock, predicted_seconds, utc
from simulator_pack.engine import completed, runtime

ROOT = Path(__file__).resolve().parents[1]
PACK_NAME = 'laptop24_pack_20261110'
SEEDS = (1, 2, 3)
MODELS = ('cnn', 'mlp')
MODES = ('none', 'masking', 'pairwise_masking', 'selective_he', 'adaptive_hybrid')
PAIR = ('none', 'adaptive_hybrid')


def job(cfg, calibration=False):
    return dict(id=('cal-' if calibration else 'sim-') + digest(cfg)[:24],
                config=cfg, config_sha256=digest(cfg))


def build():
    bundles = []

    def bundle(label, dataset, split, topology='ring', clients=20, modes=PAIR, required=False):
        jobs = [job(configuration(model, dataset, split, mode, seed, topology,
                                  alpha=.5 if split == 'dirichlet' else None, clients=clients))
                for model, mode, seed in itertools.product(MODELS, modes, SEEDS)]
        bundles.append(dict(id='bundle-' + digest([j['id'] for j in jobs])[:20],
                            label=label, required=required, jobs=jobs))

    for split in ('iid', 'dirichlet'):
        bundle('primary_cifar_' + split, 'cifar10', split, modes=MODES, required=True)
    for dataset in ('fashion_mnist', 'mnist'):
        for split in ('iid', 'dirichlet'):
            bundle('dataset_' + dataset + '_' + split, dataset, split)
    for topology in ('barabasi_albert', 'caveman'):
        bundle('topology_' + topology, 'cifar10', 'dirichlet', topology=topology)
    bundle('scaling_50', 'cifar10', 'dirichlet', clients=50)
    value = dict(format=1, style='laptop24_trusted_simulator', bundles=bundles,
                 candidate_jobs=144, required_jobs=60, seeds=list(SEEDS), rounds=20,
                 main_clients=20, optional_scaling_clients=50,
                 policy=dict(auto_start=False, wall_hours=24, reserve_hours=4,
                             planned_compute_hours=20, admission_factor=2,
                             full_datasets=True, no_test_driven_selection=True,
                             all_groups_require_three_seeds=True,
                             new_separate_campaign_not_server_migration=True,
                             trainer_has_plaintext_and_keys=True))
    value['sha256'] = digest(value)
    return value


def snapshot():
    files = dict(engine_source()['files'])
    for name in ('src/laptop24.py', 'scripts/laptop24.py', 'scripts/start_laptop24.ps1'):
        files[name] = hashlib.sha256((ROOT / name).read_text(encoding='utf-8').encode()).hexdigest()
    return dict(hash=digest(files), engine_hash=engine_source()['hash'], files=files)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def checked(pack):
    pack = Path(pack)
    manifest = load(pack / 'manifest.json')
    if manifest != build():
        raise RuntimeError('laptop manifest differs from its fixed balanced design')
    if load(pack / 'source_snapshot.json') != snapshot():
        raise RuntimeError('laptop source changed; frozen packs/checkpoints cannot be mixed')
    return manifest


def prepare(pack, cache):
    from simulator_pack.data import verify
    pack = Path(pack)
    pack.mkdir(parents=True, exist_ok=True)
    receipts = {name: verify(Path(cache) / name) for name in ('cifar10', 'mnist', 'fashion_mnist')}
    values = {'manifest.json': build(), 'source_snapshot.json': snapshot(),
              'data_snapshot.json': dict(datasets=receipts, sha256=digest(receipts))}
    for name, value in values.items():
        if (pack / name).exists() and load(pack / name) != value:
            raise RuntimeError('existing pack differs; never overwrite its frozen inputs')
    for name, value in values.items():
        atomic(pack / name, value)
    if not (pack / 'state.json').exists():
        atomic(pack / 'state.json', dict(status='prepared_not_started', started_UTC=None,
                                       deadline_UTC=None, current=None, completed=[]))
    return values['manifest.json']


def hardware():
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('laptop CUDA unavailable; no CPU fallback')
    profile = runtime('cuda')
    if '5070' not in profile['GPU'] or profile['GPU_memory_bytes'] < 7 * 1024**3:
        raise RuntimeError('this frozen design targets the RTX5070 laptop with at least7GiB VRAM')
    driver = subprocess.check_output(['nvidia-smi', '--id=0', '--query-gpu=driver_version',
                                      '--format=csv,noheader'], text=True).strip()
    return dict(engine_runtime=profile, engine_runtime_sha256=digest(profile), driver=driver)


def checked_hardware(pack):
    profile = hardware()
    if load(Path(pack) / 'hardware.json') != profile:
        raise RuntimeError('laptop runtime/driver changed; do not pool timings or resume silently')
    return profile


def preflight(pack, cache):
    import torch
    import tenseal as ts
    from simulator_pack.protection import context
    pack = Path(pack)
    checked(pack)
    check_data(pack, cache)
    profile = hardware()
    if (pack / 'hardware.json').exists() and load(pack / 'hardware.json') != profile:
        raise RuntimeError('frozen hardware profile differs')
    x = torch.ones((32, 32), device='cuda')
    y = x @ x
    torch.cuda.synchronize()
    if not torch.all(y == 32).item():
        raise RuntimeError('CUDA matrix test failed')
    ctx = context(configuration('cnn', 'cifar10', 'iid', 'selective_he', 0)['CKKS'])
    result = (ts.ckks_vector(ctx.public_context, [.25, .5]) + ts.ckks_vector(ctx.public_context, [.5, .25])).decrypt(ctx.secret_key)
    if max(abs(v - .75) for v in result) > 1e-5:
        raise RuntimeError('real CKKS addition test failed')
    atomic(pack / 'hardware.json', profile)
    atomic(pack / 'preflight.json', dict(status='passed_no_training', checked_UTC=utc(time.time()),
                                       CUDA_matmul=True, real_CKKS=True, hardware=profile))
    return profile


def clock(pack):
    pack = Path(pack)
    state = load(pack / 'state.json')
    if state['started_UTC'] is None:
        now = time.time()
        state.update(started_UTC=utc(now), deadline_UTC=utc(now + 24 * 3600))
        atomic(pack / 'state.json', state)
    return datetime.datetime.fromisoformat(state['deadline_UTC']).timestamp()


def update(pack, **values):
    state = load(Path(pack) / 'state.json')
    state.update(values)
    atomic(Path(pack) / 'state.json', state)


def calibration_jobs():
    settings = [(20, 'ring', MODES), (20, 'barabasi_albert', PAIR),
                (20, 'caveman', PAIR), (50, 'ring', PAIR)]
    for clients, topology, modes in settings:
        for model, mode in itertools.product(MODELS, modes):
            yield job(configuration(model, 'cifar10', 'dirichlet', mode, 0, topology,
                                    alpha=.5, stage='calibration', clients=clients), True)


def valid_result(pack, identifier, cfg, calibration=False):
    pack = Path(pack)
    data = load(pack / 'data_snapshot.json')['datasets'][cfg['dataset']]['receipt_sha256']
    profile = load(pack / 'hardware.json')['engine_runtime_sha256']
    return completed(pack / ('calibration' if calibration else 'results') / identifier,
                     cfg, engine_source()['hash'], profile, data)


def execute_job(pack, item, cache, deadline):
    folder = Path(pack) / ('calibration' if item['id'].startswith('cal-') else 'results') / item['id']
    if (folder / 'complete.json').exists():
        raise RuntimeError('unverified completed archive; refuse automatic retraining')
    update(pack, current=item['id'])
    try:
        child(pack, item, cache, 'cuda', deadline)
    except BaseException:
        update(pack, status='stopped_error_or_deadline')
        raise


def calibrate(pack, cache):
    pack = Path(pack).resolve()
    checked(pack)
    check_data(pack, cache)
    checked_hardware(pack)
    with lock(pack / 'controller.lock'):
        deadline = min(clock(pack), time.time() + 1800)
        update(pack, status='calibrating')
        for item in calibration_jobs():
            if valid_result(pack, item['id'], item['config'], True):
                continue
            if time.time() >= deadline or (pack / 'pause.request').exists():
                update(pack, status='paused_calibration')
                return
            execute_job(pack, item, cache, deadline)
            if not valid_result(pack, item['id'], item['config'], True):
                update(pack, status='paused_calibration')
                return
        update(pack, status='calibrated_main_not_started', current=None)


def key(cfg):
    return cfg['clients'], cfg['model'], cfg['mode'], cfg['topology']


def admit(manifest, samples, available):
    selected, excluded, total = [], [], 0.
    for bundle in manifest['bundles']:
        if not {key(j['config']) for j in bundle['jobs']} <= samples.keys():
            excluded.append(dict(bundle=bundle['id'], label=bundle['label'], reason='calibration missing'))
            continue
        costs = {j['id']: predicted_seconds(*samples[key(j['config'])], j['config']['dataset']) for j in bundle['jobs']}
        cost = sum(costs.values())
        if total + cost > available:
            excluded.append(dict(bundle=bundle['id'], label=bundle['label'],
                                 reason='outside conservative24h budget', estimated_seconds=cost))
            continue
        selected.append(dict(bundle=bundle['id'], label=bundle['label'],
                             job_ids=list(costs), job_estimated_seconds=costs, estimated_seconds=cost))
        total += cost
    required = {b['id'] for b in manifest['bundles'] if b['required']}
    return dict(status='ready' if required <= {b['bundle'] for b in selected} else 'insufficient_budget_or_calibration',
                selected=selected, excluded=excluded, estimated_seconds=total,
                required_bundle_ids=sorted(required))


def plan(pack):
    pack = Path(pack)
    manifest = checked(pack)
    if (pack / 'selected_plan.json').exists():
        selection = load(pack / 'selected_plan.json')
        validate_selection(pack, selection)
        return selection
    samples = {}
    for item in calibration_jobs():
        folder = pack / 'calibration' / item['id']
        if valid_result(pack, item['id'], item['config'], True):
            samples[key(item['config'])] = (load(folder / 'complete.json'), load(folder / 'metrics.json'))
        elif (folder / 'complete.json').exists():
            raise RuntimeError('calibration integrity/provenance failure')
    state = load(pack / 'state.json')
    if state['deadline_UTC'] is None:
        raise RuntimeError('calibration has not started; no measured admission possible')
    available = min(20 * 3600, datetime.datetime.fromisoformat(state['deadline_UTC']).timestamp() - time.time() - 4 * 3600)
    value = admit(manifest, samples, available)
    value.update(available_seconds=available, deadline_UTC=state['deadline_UTC'],
                 manifest_sha256=manifest['sha256'], laptop_source_hash=snapshot()['hash'],
                 hardware_sha256=digest(load(pack / 'hardware.json')),
                 assumptions='2x measured CIFAR stage costs; grayscale1.5x CIFAR; count/topology-specific calibration; seed0 excluded; no accuracy-based admission')
    value['sha256'] = digest(value)
    atomic(pack / ('selected_plan.json' if value['status'] == 'ready' else 'admission_blocked.json'), value)
    return value


def validate_selection(pack, selection):
    if (selection['sha256'] != digest({k: v for k, v in selection.items() if k != 'sha256'})
            or selection['manifest_sha256'] != build()['sha256']
            or selection['laptop_source_hash'] != snapshot()['hash']
            or selection['hardware_sha256'] != digest(load(Path(pack) / 'hardware.json'))
            or selection['deadline_UTC'] != load(Path(pack) / 'state.json')['deadline_UTC']):
        raise RuntimeError('selected plan provenance differs')


def run(pack, cache):
    pack = Path(pack).resolve()
    manifest = checked(pack)
    check_data(pack, cache)
    checked_hardware(pack)
    selection = load(pack / 'selected_plan.json')
    validate_selection(pack, selection)
    if selection['status'] != 'ready':
        raise RuntimeError('primary comparison not admitted')
    jobs = {j['id']: j for b in manifest['bundles'] for j in b['jobs']}
    with lock(pack / 'controller.lock'):
        deadline = clock(pack)
        for bundle in selection['selected']:
            pending = [i for i in bundle['job_ids'] if not valid_result(pack, i, jobs[i]['config'])]
            if (time.time() + sum(bundle['job_estimated_seconds'][i] for i in pending) > deadline - 1800
                    or (pack / 'pause.request').exists()):
                break
            for identifier in pending:
                if time.time() >= deadline or (pack / 'pause.request').exists():
                    break
                import shutil
                if shutil.disk_usage(pack).free < 16 * 1024**3:
                    raise RuntimeError('free disk below16GiB; no new run started')
                checked_hardware(pack)
                update(pack, status='running')
                execute_job(pack, jobs[identifier], cache, deadline)
                if not valid_result(pack, identifier, jobs[identifier]['config']):
                    update(pack, status='paused_or_deadline_reached')
                    return
        actual = status(pack)
        update(pack, status='selected_series_completed' if actual['verified_completed'] == actual['selected_jobs'] else 'paused_or_budget_exhausted',
               current=None)


def status(pack):
    pack = Path(pack)
    manifest = checked(pack)
    state = load(pack / 'state.json')
    selection = load(pack / 'selected_plan.json') if (pack / 'selected_plan.json').exists() else None
    if selection:
        validate_selection(pack, selection)
    jobs = {j['id']: j for b in manifest['bundles'] for j in b['jobs']}
    ids = [i for b in selection['selected'] for i in b['job_ids']] if selection else []
    done = sum(valid_result(pack, i, jobs[i]['config']) for i in ids)
    calibrated = sum(valid_result(pack, j['id'], j['config'], True) for j in calibration_jobs()) if (pack / 'hardware.json').exists() else 0
    return dict(stage=state['status'], candidate_jobs=144, required_jobs=60, selected_jobs=len(ids),
                verified_completed=done, selected_pending=len(ids)-done,
                verified_calibrations=calibrated, planned_calibrations=22,
                started_UTC=state['started_UTC'], deadline_UTC=state['deadline_UTC'], current=state['current'])


def summarize(pack):
    pack = Path(pack)
    manifest = checked(pack)
    groups = {}
    for bundle in manifest['bundles']:
        for item in bundle['jobs']:
            cfg = item['config']
            if not valid_result(pack, item['id'], cfg):
                continue
            receipt = load(pack / 'results' / item['id'] / 'complete.json')
            group_key = tuple(cfg[n] for n in ('clients', 'model', 'dataset', 'split', 'alpha', 'topology', 'mode', 'HE_ratio'))
            groups.setdefault(group_key, []).append((item['id'], receipt))
    rows = []
    for group_key, items in sorted(groups.items(), key=lambda x: str(x[0])):
        complete = len(items) == 3 and {r['config']['seed'] for _, r in items} == set(SEEDS)
        row = dict(setting=dict(zip(('clients', 'model', 'dataset', 'split', 'alpha', 'topology', 'mode', 'HE_ratio'), group_key)),
                   seeds=sorted(r['config']['seed'] for _, r in items), n=len(items), complete_three_seeds=complete,
                   statistics=None, validation_curve=[])
        if complete:
            stats = lambda x: dict(mean=statistics.mean(x), sample_SD=statistics.stdev(x))
            row['statistics'] = {name: stats([r['final_test'][name] for _, r in items]) for name in ('accuracy', 'loss')}
            durations = [r['recorded_job_seconds'] for _, r in items]
            row['statistics']['recorded_job_seconds'] = stats(durations) if all(x is not None for x in durations) else None
            rounds = [load(pack / 'results' / identifier / 'metrics.json') for identifier, _ in items]
            for index in (4, 9, 14, 19):
                row['validation_curve'].append(dict(round=index+1, accuracy=stats([r[index]['validation']['accuracy'] for r in rounds])))
        rows.append(row)
    value = dict(status=status(pack), groups=rows, historical_results_pooled=False,
                 runtime=load(pack / 'hardware.json'), laptop_source_hash=snapshot()['hash'],
                 interpretation='Full-data20round trusted simulator; complete3seed statistics only; no guaranteed accuracy; client-count changes affect partitions and learning, not only speed')
    atomic(pack / 'summary.json', value)
    return value
