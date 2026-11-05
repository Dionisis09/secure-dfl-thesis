"""Real OpenFHE and mTLS integration gate. No training, no legacy mode substitution."""
import argparse,json,sys,time,dataclasses,ssl,http.client
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from secure_protocol_v4.core import RoundSpec,Rejected,encode,decode
from secure_protocol_v4.transport import Group

def exercise(kind,n):
    start=time.monotonic();roster=tuple(f'p{i:03}' for i in range(n))
    spec=RoundSpec('integration-v4','fresh-key-epoch',roster[0],1,'model-head','10x256+10',roster,2570,kind)
    rng=np.random.default_rng(77);v={name:rng.uniform(-.1,.1,2570).tolist() for name in roster};checks=[]
    with Group(spec,v,testing=True) as group:
        if kind=='he_bfv':group.keygen()
        setup=time.monotonic()-start;messages=group.contributions();candidate=group.average(messages)
        def denied(label,op,**args):
            try:group.call(spec.target,op,**args)
            except Rejected:checks.append(label);return
            raise AssertionError('Accepted forbidden request: '+label)
        denied('individual_ciphertext','approve',messages=messages,candidate=messages[0]['body']['payload']['data'])
        denied('missing_contributor','approve',messages=messages[:-1],candidate=encode(candidate))
        denied('duplicate_contributor','approve',messages=messages[:-1]+[messages[0]],candidate=encode(candidate))
        corrupt=json.loads(json.dumps(messages));corrupt[1]['body']['context']='wrong-round'
        denied('wrong_round','approve',messages=corrupt,candidate=encode(candidate))
        corrupt=json.loads(json.dumps(messages));corrupt[1]['body']['payload']['data']=encode(b'tampered')
        denied('modified_contribution','approve',messages=corrupt,candidate=encode(candidate))
        denied('raw_decryption_endpoint','decrypt',ciphertext=messages[0]['body']['payload']['data'])
        denied('release_before_approval','release',messages=messages,candidate=encode(candidate),approvals=[])
        # Wrong but CA-authorized client identity must still be denied by the RPC role policy.
        ctx=ssl.create_default_context(cafile=str(group.folder/'ca.pem'))
        ctx.load_cert_chain(str(group.folder/(roster[1]+'.pem')),str(group.folder/(roster[1]+'.key')))
        conn=http.client.HTTPSConnection('localhost',group.addresses[spec.target],context=ctx,timeout=10)
        conn.request('POST','/rpc',json.dumps({'op':'contribute'}));response=conn.getresponse();response.read();assert response.status==400;conn.close();checks.append('wrong_mtls_client')
        # No client cert is rejected during TLS or before HTTP response.
        ctx=ssl.create_default_context(cafile=str(group.folder/'ca.pem'))
        conn=http.client.HTTPSConnection('localhost',group.addresses[spec.target],context=ctx,timeout=10)
        try:
            conn.request('POST','/rpc',json.dumps({'op':'contribute'}));r=conn.getresponse();r.read();assert r.status!=200
        except (ssl.SSLError,ConnectionError,http.client.HTTPException):pass
        finally:conn.close()
        checks.append('missing_mtls_client_certificate')
        if kind=='he_bfv':
            assert group.call(spec.target,'probe') is False;checks.append('single_private_share_cannot_recover_own_ciphertext')
        result=group.finish(messages,candidate);error=float(np.max(np.abs(result-np.mean(list(v.values()),axis=0))))
        assert error<(1e-5 if kind=='he_bfv' else 1/spec.scale),(kind,error)
        denied('approval_replay','approve',messages=messages,candidate=encode(candidate))
        denied('release_replay','release',messages=messages,candidate=encode(candidate),approvals=group.last_approvals)
        denied('duplicate_contribution_replay','contribute')
        assert len(set(group.pids.values()))==n
        report=dict(kind=kind,participants=n,processes=n,length=2570,max_absolute_error=error,setup_seconds=setup,total_seconds=time.monotonic()-start,negative_checks=checks,mtls=True,no_aggregator_private_key=True,scope='One all-party aggregate, trusted host/passive peers, not full DFL training or independent-host isolation')
        if group.crypto:report['ring_dimension']=group.crypto.cc.GetRingDimension()
        report.update(serialized_contribution_bytes=sum(len(decode(m['body']['payload']['data'])) for m in messages),aggregate_bytes=len(candidate),rpc_json_request_bytes=group.request_bytes,rpc_json_response_bytes=group.response_bytes,rpc_requests=group.request_count,traffic_scope='JSON application payloads only; excludes TLS/HTTP headers and independently-issued negative TLS probes')
    return report
def main():
    p=argparse.ArgumentParser();p.add_argument('--participants',type=int,default=3);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    reports=[]
    for kind in ['pairwise','he_bfv']:
        r=exercise(kind,a.participants);reports.append(r);print(json.dumps(r),flush=True)
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(dict(status='verified' if len(reports)==2 else 'partial',reports=reports),indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
