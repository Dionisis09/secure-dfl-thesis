"""Read-only live coverage from verified receipts, not cached counters."""
import argparse,datetime,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from simulator_pack.design import validate,digest
from simulator_pack.engine import completed

def status(pack):
    pack=Path(pack);manifest=validate(json.loads((pack/'manifest.json').read_text()));state=json.loads((pack/'state.json').read_text())
    source=json.loads((pack/'source_snapshot.json').read_text())['hash'];jobs={j['id']:j for b in manifest['bundles'] for j in b['jobs']}
    plan_file=pack/'selected_plan.json';selection=json.loads(plan_file.read_text()) if plan_file.exists() else None
    if selection and selection['sha256']!=digest({k:v for k,v in selection.items() if k!='sha256'}):raise RuntimeError('selection hash mismatch')
    ids=[i for b in selection['selected'] for i in b['job_ids']] if selection else [];done=set();invalid=[]
    for i in ids:
        folder=pack/'results'/i
        if completed(folder,jobs[i]['config'],source):done.add(i)
        elif (folder/'complete.json').exists():invalid.append(i)
    calibrated=sum(completed(d,expected_source=source) for d in (pack/'calibration').glob('cal-*'))
    active=None
    if state.get('current'):
        folder=pack/('calibration' if state['current'].startswith('cal-') else 'results')/state['current'];p=folder/'progress.json'
        if p.exists():
            value=json.loads(p.read_text());active=dict(job=state['current'],completed_rounds=value['completed'],planned_rounds=value['planned'])
        else:active=dict(job=state['current'],stage='startup_or_first_round')
    value=dict(stage=state['status'],candidate_runs=manifest['candidate_jobs'],selected_runs=len(ids),verified_completed_runs=len(done),selected_pending=len(ids)-len(done),
        selected_bundles=len(selection['selected']) if selection else 0,complete_paired_bundles=sum(set(b['job_ids'])<=done for b in selection['selected']) if selection else 0,
        verified_calibration_jobs=calibrated,calibration_seed=0,scientific_seeds=[1,2,3],invalid_completed_archives=invalid,active=active,deadline_UTC=state['deadline_UTC'])
    if manifest.get('scaling'):
        s=manifest['scaling'];cases=set(s['new_job_ids']+s['reference_50_job_ids'])
        value['scaling']=dict(client_counts=s['client_counts'],required_cases=36,new_jobs=24,reused_50_jobs=12,
            selected_cases=len(cases&set(ids)),verified_completed_cases=len(cases&done),requires_fresh_RTX4090_calibration=True)
        value['remaining_wall_hours']=max(0,(__import__('datetime').datetime.fromisoformat(state['deadline_UTC']).timestamp()-__import__('time').time())/3600)
    return value

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pack',required=True);a=p.parse_args();print(json.dumps(status(a.pack),indent=2))
