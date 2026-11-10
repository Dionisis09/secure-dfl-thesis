"""Prespecified CIFAR convergence/heterogeneity study with a fixed eight-hour cap."""
import datetime
import hashlib
import itertools
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

import laptop24 as lp
from simulator_pack.campaign import check_data, lock, utc
from simulator_pack.data import verify
from simulator_pack.design import atomic, configuration, digest

ROOT = lp.ROOT
PACK_NAME = 'overnight8_pack_20261110'
REFERENCE = ROOT / lp.PACK_NAME
SETTINGS = [('iid', None), ('dirichlet', .5), ('dirichlet', .1)]


def cfg(model, mode, seed, split, alpha, calibration=False):
    c = configuration(model, 'cifar10', split, mode, seed, alpha=alpha,
                      stage='calibration' if calibration else 'convergence', clients=20)
    c.update(rounds=2 if calibration else 60, schedule_rounds=60)
    return c


def build():
    bundles = []
    for split, alpha in SETTINGS:
        jobs = [lp.job(cfg(model, mode, seed, split, alpha))
                for model, mode, seed in itertools.product(lp.MODELS, lp.PAIR, lp.SEEDS)]
        bundles.append(dict(id='bundle-' + digest([j['id'] for j in jobs])[:20],
                            split=split, alpha=alpha, required=alpha != .1, jobs=jobs))
    value = dict(format=1, study='overnight8_convergence', candidate_jobs=36, required_jobs=24,
                 bundles=bundles, rounds=60, schedule_rounds=60, clients=20, seeds=[1,2,3],
                 policy=dict(wall_hours=8, reserve_hours=1, compute_hours=7, cost_factor=2,
                             all_groups_require_three_seeds=True, full_dataset=True,
                             no_test_driven_selection=True, trainer_has_plaintexts_and_keys=True,
                             fresh_training_from_common_seed=True, auto_restart_clock=False))
    value['sha256'] = digest(value)
    return value


def snapshot():
    files = dict(lp.snapshot()['files'])
    for name in ('src/overnight8.py', 'scripts/overnight8.py', 'scripts/start_overnight8.ps1'):
        files[name] = hashlib.sha256((ROOT/name).read_text(encoding='utf-8').encode()).hexdigest()
    return dict(hash=digest(files), engine_hash=lp.engine_source()['hash'], files=files)


def reference_jobs():
    return [j for b in lp.build()['bundles'] for j in b['jobs']
            if j['config']['dataset']=='cifar10' and j['config']['clients']==20
            and j['config']['topology']=='ring' and j['config']['mode'] in lp.PAIR]


def references():
    lp.checked(REFERENCE)
    rows = []
    for item in reference_jobs():
        if not lp.valid_result(REFERENCE, item['id'], item['config']):
            raise RuntimeError('required20round reference archive invalid')
        folder = REFERENCE/'results'/item['id']
        rows.append(dict(id=item['id'], files={n: hashlib.sha256((folder/n).read_bytes()).hexdigest()
                    for n in ('complete.json','metrics.json','identity.json','checksums.json')}))
    value = dict(pack=lp.PACK_NAME, rows=rows)
    value['sha256'] = digest(value)
    return value


def checked(pack):
    pack = Path(pack)
    if lp.load(pack/'manifest.json') != build() or lp.load(pack/'source_snapshot.json') != snapshot():
        raise RuntimeError('frozen overnight source/design differs')
    if lp.load(pack/'reference_snapshot.json') != references():
        raise RuntimeError('measured reference source/data/results differ')
    return build()


def prepare(pack, cache):
    pack = Path(pack)
    pack.mkdir(parents=True, exist_ok=True)
    profile = lp.hardware()
    if profile != lp.load(REFERENCE/'hardware.json'):
        raise RuntimeError('actual laptop driver/runtime differs from timing references')
    receipt = verify(Path(cache)/'cifar10')
    if receipt != lp.load(REFERENCE/'data_snapshot.json')['datasets']['cifar10']:
        raise RuntimeError('CIFAR fold/cache differs from completed20round study')
    datasets = dict(cifar10=receipt)
    values = {'manifest.json': build(), 'source_snapshot.json': snapshot(),
              'reference_snapshot.json': references(), 'hardware.json': profile,
              'data_snapshot.json': dict(datasets=datasets, sha256=digest(datasets))}
    for name, value in values.items():
        if (pack/name).exists() and lp.load(pack/name) != value:
            raise RuntimeError('existing overnight pack differs; preserve its frozen inputs')
    for name, value in values.items():
        atomic(pack/name, value)
    if not (pack/'state.json').exists():
        atomic(pack/'state.json', dict(status='prepared_not_started', started_UTC=None,
                                      deadline_UTC=None, current=None))
    return build()


def clock(pack):
    state = lp.load(Path(pack)/'state.json')
    if state['started_UTC'] is None:
        now = time.time()
        lp.update(pack, started_UTC=utc(now), deadline_UTC=utc(now+8*3600))
        return now+8*3600
    start = datetime.datetime.fromisoformat(state['started_UTC']).timestamp()
    end = datetime.datetime.fromisoformat(state['deadline_UTC']).timestamp()
    if not 0 < end-start <= 8*3600:
        raise RuntimeError('invalid8hour clock; no extension allowed')
    return end


def calibrations():
    return [lp.job(cfg(model, mode, 0, 'dirichlet', .1, True), True)
            for model, mode in itertools.product(lp.MODELS, lp.PAIR)]


def key(c):
    return c['model'], c['mode'], c['split'], c['alpha']


def predicted(receipt, records):
    if not records or not all(r['timing_complete'] for r in records):
        raise RuntimeError('incomplete measured stage timings')
    stages = sum(statistics.mean(r[n] for r in records) for n in
                 ('training_seconds','aggregation_seconds','snapshot_seconds','load_seconds','checkpoint_seconds'))
    validation = [r['validation_seconds'] for r in records if r['validation'] is not None]
    if not validation:
        raise RuntimeError('validation timing missing')
    return 2*(receipt['setup_seconds']+60*stages+12*statistics.mean(validation)
              +receipt['test_final_seconds']+receipt['test_best_seconds']+5)


def costs(pack):
    result = {}
    for item in reference_jobs():
        folder = REFERENCE/'results'/item['id']
        result.setdefault(key(item['config']), []).append(predicted(lp.load(folder/'complete.json'), lp.load(folder/'metrics.json')))
    for item in calibrations():
        folder = Path(pack)/'calibration'/item['id']
        if lp.valid_result(pack, item['id'], item['config'], True):
            result.setdefault(key(item['config']), []).append(predicted(lp.load(folder/'complete.json'), lp.load(folder/'metrics.json')))
        elif (folder/'complete.json').exists():
            raise RuntimeError('alpha0.1 calibration archive invalid')
    return {k: max(v) for k,v in result.items()}


def admit(manifest, estimates, available):
    selected, excluded, total = [], [], 0.
    for bundle in manifest['bundles']:
        jobs = bundle['jobs']
        if not {key(j['config']) for j in jobs} <= estimates.keys():
            excluded.append(dict(bundle=bundle['id'], reason='calibration missing'))
            continue
        cost = sum(estimates[key(j['config'])] for j in jobs)
        if total+cost > available:
            excluded.append(dict(bundle=bundle['id'], reason='does not fit8hour budget', estimated_seconds=cost))
            continue
        selected.append(dict(bundle=bundle['id'], job_ids=[j['id'] for j in jobs],
                             estimated_seconds=cost, job_estimated_seconds={j['id']: estimates[key(j['config'])] for j in jobs}))
        total += cost
    required = {b['id'] for b in manifest['bundles'] if b['required']}
    return dict(status='ready' if required <= {b['bundle'] for b in selected} else 'admission_blocked',
                selected=selected, excluded=excluded, estimated_seconds=total)


def plan(pack):
    pack = Path(pack)
    manifest = checked(pack)
    if (pack/'selected_plan.json').exists():
        selection = lp.load(pack/'selected_plan.json')
        validate_plan(pack, selection)
        return selection
    deadline = clock(pack)
    value = admit(manifest, costs(pack), min(7*3600, deadline-time.time()-3600))
    value.update(deadline_UTC=lp.load(pack/'state.json')['deadline_UTC'],
                 manifest_sha256=manifest['sha256'], source_hash=snapshot()['hash'],
                 hardware_sha256=digest(lp.load(pack/'hardware.json')),
                 reference_sha256=lp.load(pack/'reference_snapshot.json')['sha256'],
                 assumptions='2x max-seed measured stages projected to60rounds/12validation checks; alpha0.1 measured separately; setup/test constant; no accuracy-based admission')
    value['sha256'] = digest(value)
    atomic(pack/('selected_plan.json' if value['status']=='ready' else 'admission_blocked.json'), value)
    return value


def validate_plan(pack, selection):
    if (selection['sha256'] != digest({k:v for k,v in selection.items() if k!='sha256'})
            or selection['manifest_sha256'] != build()['sha256']
            or selection['source_hash'] != snapshot()['hash']
            or selection['hardware_sha256'] != digest(lp.load(Path(pack)/'hardware.json'))
            or selection['reference_sha256'] != lp.load(Path(pack)/'reference_snapshot.json')['sha256']
            or selection['deadline_UTC'] != lp.load(Path(pack)/'state.json')['deadline_UTC']):
        raise RuntimeError('overnight selection provenance differs')


def stop_child(process):
    """Stop only our training subtree, including the Windows venv redirector."""
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def execute_job(pack, item, cache, deadline):
    pack = Path(pack)
    folder = pack/('calibration' if item['id'].startswith('cal-') else 'results')/item['id']
    if (folder/'complete.json').exists():
        raise RuntimeError('unverified completed archive; no automatic retraining')
    folder.mkdir(parents=True, exist_ok=True)
    atomic(folder/'request.json', item['config'])
    lp.update(pack, current=item['id'])
    argv = [sys.executable,'-u',str(ROOT/'scripts/simulator50.py'),'_job',
            '--config',str(folder/'request.json'),'--output',str(folder),
            '--cache',str(Path(cache).resolve()),'--device','cuda','--deadline',str(deadline)]
    with (folder/'runner.log').open('ab') as log:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            while process.poll() is None:
                if time.time() >= deadline:
                    stop_child(process)
                    raise TimeoutError('overnight deadline reached; last atomic checkpoint retained')
                if (pack/'pause.request').exists() or shutil.disk_usage(pack).free < 12*1024**3:
                    (folder/'pause.request').touch()
                time.sleep(1)
            if process.returncode:
                raise RuntimeError('training failed; checkpoint retained; inspect '+str(folder/'runner.log'))
        finally:
            if process.poll() is None:
                stop_child(process)


def status(pack):
    pack = Path(pack)
    manifest = checked(pack)
    state = lp.load(pack/'state.json')
    selection = lp.load(pack/'selected_plan.json') if (pack/'selected_plan.json').exists() else None
    if selection:
        validate_plan(pack, selection)
    jobs = {j['id']:j for b in manifest['bundles'] for j in b['jobs']}
    ids = [i for b in selection['selected'] for i in b['job_ids']] if selection else []
    done = sum(lp.valid_result(pack, i, jobs[i]['config']) for i in ids)
    return dict(stage=state['status'], selected_runs=len(ids), verified_completed=done,
                pending=len(ids)-done, candidate_runs=36, rounds=60,
                verified_calibrations=sum(lp.valid_result(pack, j['id'], j['config'], True) for j in calibrations()),
                current=state['current'], started_UTC=state['started_UTC'], deadline_UTC=state['deadline_UTC'])


def summarize(pack):
    pack = Path(pack)
    manifest = checked(pack)
    groups = {}
    for bundle in manifest['bundles']:
        for item in bundle['jobs']:
            c = item['config']
            if lp.valid_result(pack, item['id'], c):
                groups.setdefault(key(c), []).append(item)
    rows = []
    for k, items in sorted(groups.items(), key=lambda x:str(x[0])):
        complete = len(items)==3 and {j['config']['seed'] for j in items}=={1,2,3}
        row = dict(model=k[0], mode=k[1], split=k[2], alpha=k[3], n=len(items),
                   seeds=sorted(j['config']['seed'] for j in items), complete_three_seeds=complete,
                   statistics=None, validation_curve=[])
        if complete:
            receipts = [lp.load(pack/'results'/j['id']/'complete.json') for j in items]
            stats = lambda values: dict(mean=statistics.mean(values), sample_SD=statistics.stdev(values))
            row['statistics'] = {n: stats([r['final_test'][n] for r in receipts]) for n in ('accuracy','loss')}
            row['statistics']['recorded_job_seconds'] = stats([r['recorded_job_seconds'] for r in receipts]) if all(r['recorded_job_seconds'] is not None for r in receipts) else None
            records = [lp.load(pack/'results'/j['id']/'metrics.json') for j in items]
            row['validation_curve'] = [dict(round=i+1, accuracy=stats([r[i]['validation']['accuracy'] for r in records])) for i in range(4,60,5)]
        rows.append(row)
    value = dict(status=status(pack), groups=rows, hardware=lp.load(pack/'hardware.json'),
                 interpretation='Fresh60round training with60round cosine schedule; comparison to20round study changes both horizon and LR schedule. Same60round trajectory validation at20/40/60 measures continued convergence. Test is not used for tuning/admission. Trusted trainer retains plaintexts/keys.')
    atomic(pack/'summary.json', value)
    return value


def start(pack, cache):
    pack = Path(pack).resolve()
    checked(pack)
    check_data(pack, cache)
    lp.checked_hardware(pack)
    with lock(pack/'controller.lock'):
        deadline = clock(pack)
        if time.time() >= deadline:
            lp.update(pack, status='stopped_at8hour_deadline')
            return status(pack)
        if (pack/'pause.request').exists():
            lp.update(pack, status='paused')
            return status(pack)
        try:
            if not (pack/'selected_plan.json').exists():
                lp.update(pack, status='calibrating_alpha0.1')
                cap = min(deadline, time.time()+600)
                for item in calibrations():
                    if lp.valid_result(pack, item['id'], item['config'], True):
                        continue
                    if time.time() >= cap or (pack/'pause.request').exists():
                        lp.update(pack, status='paused_calibration')
                        return status(pack)
                    execute_job(pack, item, cache, cap)
                    if not lp.valid_result(pack, item['id'], item['config'], True):
                        lp.update(pack, status='paused_calibration')
                        return status(pack)
            selection = plan(pack)
            if selection['status'] != 'ready':
                lp.update(pack, status='admission_blocked', current=None)
                return status(pack)
            jobs = {j['id']:j for b in build()['bundles'] for j in b['jobs']}
            for bundle in selection['selected']:
                pending = [i for i in bundle['job_ids'] if not lp.valid_result(pack, i, jobs[i]['config'])]
                if (time.time()+sum(bundle['job_estimated_seconds'][i] for i in pending) > deadline-300
                        or (pack/'pause.request').exists()):
                    break
                for i in pending:
                    if time.time() >= deadline or (pack/'pause.request').exists():
                        break
                    if shutil.disk_usage(pack).free < 16*1024**3:
                        raise RuntimeError('free disk below16GiB; no run started')
                    lp.checked_hardware(pack)
                    lp.update(pack, status='running')
                    execute_job(pack, jobs[i], cache, deadline)
                    if not lp.valid_result(pack, i, jobs[i]['config']):
                        lp.update(pack, status='paused_or_deadline_reached')
                        return status(pack)
            actual = status(pack)
            lp.update(pack, status='selected_series_completed' if actual['verified_completed']==actual['selected_runs'] else 'paused_or_budget_exhausted', current=None)
            summarize(pack)
        except TimeoutError:
            lp.update(pack, status='stopped_at_deadline_or_calibration_cap')
        except BaseException:
            lp.update(pack, status='stopped_error_checkpoint_retained')
            raise
    return status(pack)
