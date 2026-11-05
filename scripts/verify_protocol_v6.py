"""Verified HE functional/attack gate; synthetic inputs, not model training."""
import argparse,copy,hashlib,http.client,importlib.metadata,json,os,platform,ssl,sys,time
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from secure_protocol_v6.node import RoundSpec
from secure_protocol_v6.transport import Group
from secure_protocol_v6 import crypto as c
from secure_protocol_v6 import rangeproof as rp
from secure_protocol_v4.core import Rejected,encode,decode,verify,aggregate_tag

def run(n,length,parallelism,output):
    start=time.monotonic();roster=tuple(f'p{i:03}' for i in range(n))
    spec=RoundSpec('integration-v5','fresh-key-epoch',roster[0],1,'head-model','head-10x256+bias10' if length==2570 else 'test-vector',roster,length)
    rng=np.random.default_rng(77);values={name:rng.uniform(-.1,.1,length).tolist() for name in roster}
    for i,name in enumerate(roster):
        edge=[spec.bound,-spec.bound,0,(-1)**i*spec.bound,.5/spec.scale,-.5/spec.scale]
        values[name][:min(length,len(edge))]=edge[:length]
    checks=[];phases={}
    def stage(name):print(json.dumps(dict(stage=name,elapsed_seconds=time.monotonic()-start)),flush=True)
    stage('starting_processes')
    with Group(spec,values,testing=True,parallelism=parallelism) as group:
        stage('key_proofs');keys=group.keygen()
        def denied(label,name,op,**args):
            try:group.call(name,op,**args)
            except Rejected:checks.append(label);return
            raise AssertionError('forbidden operation accepted: '+label)
        # Legitimately signed rogue-key attempt: its sum would equal the attacker's
        # original standalone public key, but the attacker cannot prove its secret.
        raw=decode(keys[-1]['body']['payload']['data']);others=c.IDENTITY
        for key in keys[:-1]:others=c.add(others,decode(key['body']['payload']['data'])[:32])
        rogue=c.sub(raw[:32],others)+raw[32:]
        forged=group.call(roster[-1],'test_forge',phase='keyshare',payload={'data':encode(rogue)})
        verify(forged,spec,'keyshare',group.roster)
        denied('signed_rogue_final_key_rejected',roster[0],'set_keys',messages=keys[:-1]+[forged])
        denied('caller_supplied_joint_key_rejected',roster[0],'set_keys',messages=keys,joint_key=encode(raw[:32]))
        group.set_keys();assert group.public!=raw[:32]
        phases['setup_seconds']=time.monotonic()-start
        stage('encrypting_and_proving_inputs');t=time.monotonic();messages=group.contributions();phases['contribution_seconds']=time.monotonic()-t
        candidate=group.average(messages)
        # Cancel every other honest contribution except one victim; copied proof
        # bytes are fresh-signed by the corrupt client, so signature checks alone
        # cannot be the reason for rejection.
        to_cancel=[decode(m['body']['payload']['data']) for m in messages[2:]]
        cancelled=c.aggregate(to_cancel,length);own=decode(messages[0]['body']['payload']['data']);attack=[]
        for (i,(R,C)),(_,record) in zip(c.chunks(cancelled,64,length),c.chunks(own,288,length)):
            attack.append(c.sub(c.IDENTITY,R)+c.sub(c.IDENTITY,C)+b''.join(record[2:]))
        forged=group.call(roster[0],'test_forge',phase='contribution',payload={'data':encode(b''.join(attack)),'range_proof':messages[0]['body']['payload']['range_proof']})
        verify(forged,spec,'contribution',group.roster)
        denied('fresh_signed_ciphertext_cancellation_rejected',roster[1],'approve',messages=[forged]+messages[1:],candidate=encode(candidate))
        forged=group.call(roster[0],'test_forge',phase='contribution',payload={'data':encode(own[:-1]),'range_proof':messages[0]['body']['payload']['range_proof']})
        denied('missing_ciphertext_proof_rejected',roster[1],'approve',messages=[forged]+messages[1:],candidate=encode(candidate))
        forged=group.call(roster[0],'test_forge',phase='contribution',payload={'data':encode(b'\xff'*32+own[32:]),'range_proof':messages[0]['body']['payload']['range_proof']})
        denied('fresh_signed_invalid_group_element_rejected',roster[1],'approve',messages=[forged]+messages[1:],candidate=encode(candidate))
        forged=group.call(roster[0],'test_forge',phase='contribution',payload={'data':encode(own)})
        denied('missing_range_proof_rejected',roster[1],'approve',messages=[forged]+messages[1:],candidate=encode(candidate))
        proof=decode(messages[0]['body']['payload']['range_proof'])
        forged=group.call(roster[0],'test_forge',phase='contribution',payload={'data':encode(own),'range_proof':encode(proof[:-1])})
        denied('tampered_range_proof_rejected',roster[1],'approve',messages=[forged]+messages[1:],candidate=encode(candidate))
        from secure_protocol_v4.core import digest,canonical
        key_id=bytes.fromhex(digest(canonical(sorted(keys,key=lambda m:m['body']['sender']))))
        for sign,label in [(1,'upper'),(-1,'lower')]:
            integers=[sign*(rp.bound_integer(spec)+1)]*length
            data,blindings=c._encrypt_records(integers,spec,group.public,key_id,roster[0])
            wrong_proof=rp.prove([0]*length,blindings,spec,c.range_context(data,spec,key_id,roster[0]))
            forged=group.call(roster[0],'test_forge',phase='contribution',payload={'data':encode(data),'range_proof':encode(wrong_proof)})
            verify(forged,spec,'contribution',group.roster)
            denied('valid_signed_'+label+'_bound_violation_rejected',roster[1],'approve',messages=[forged]+messages[1:],candidate=encode(candidate))
        denied('missing_contributor',roster[0],'approve',messages=messages[:-1],candidate=encode(candidate))
        denied('duplicate_contributor',roster[0],'approve',messages=messages[:-1]+[messages[0]],candidate=encode(candidate))
        denied('raw_decryption_endpoint',roster[0],'decrypt',ciphertext=encode(candidate))
        assert group.call(roster[0],'test_single_share') is False;checks.append('single_private_share_not_full_decryption_key')
        # Wrong but CA-authorized TLS identity is rejected independently of proofs.
        tls=ssl.create_default_context(cafile=str(group.folder/'ca.pem'))
        tls.load_cert_chain(str(group.folder/(roster[1]+'.pem')),str(group.folder/(roster[1]+'.key')))
        conn=http.client.HTTPSConnection('localhost',group.addresses[roster[0]],context=tls,timeout=10)
        conn.request('POST','/rpc',json.dumps({'op':'contribute','args':{}}),{'Content-Type':'application/json'});response=conn.getresponse();response.read();assert response.status==400;conn.close();checks.append('wrong_mtls_client')
        tls=ssl.create_default_context(cafile=str(group.folder/'ca.pem'));conn=http.client.HTTPSConnection('localhost',group.addresses[roster[0]],context=tls,timeout=10)
        try:
            conn.request('POST','/rpc',json.dumps({'op':'contribute','args':{}}),{'Content-Type':'application/json'});response=conn.getresponse();response.read();assert response.status!=200
        except (ssl.SSLError,ConnectionError,http.client.HTTPException):pass
        finally:conn.close()
        checks.append('missing_client_certificate')
        stage('verifying_all_ciphertext_proofs_and_approving');t=time.monotonic();approvals=group.approvals(messages,candidate);phases['approval_seconds']=time.monotonic()-t
        denied('missing_approval',roster[0],'release',messages=messages,candidate=encode(candidate),approvals=approvals[:-1])
        individual=b''.join(record[0]+record[1] for _,record in c.chunks(own,288,length))
        denied('individual_ciphertext_release_rejected',roster[0],'release',messages=messages,candidate=encode(individual),approvals=approvals)
        stage('producing_decryption_share_proofs');t=time.monotonic();releases=group.releases(messages,candidate,approvals);phases['release_seconds']=time.monotonic()-t
        tag=aggregate_tag(spec,messages,encode(candidate));data=decode(releases[0]['body']['payload']['data'])
        invalid=c.add(data[:32],c.base(c.scalar(1)))+data[32:]
        try:c.verify_partial(invalid,candidate,spec,decode(keys[0]['body']['payload']['data'])[:32],tag,roster[0])
        except Rejected:checks.append('altered_decryption_share_proof_rejected')
        else:raise AssertionError('invalid decryption share accepted')
        stage('verifying_decryption_shares_and_decoding');t=time.monotonic();result=np.asarray(group.recover(messages,candidate,releases));phases['fusion_decode_seconds']=time.monotonic()-t
        expected=np.mean(list(values.values()),axis=0);error=float(np.max(np.abs(result-expected)))
        quantized=np.mean(np.rint(np.asarray(list(values.values()))*spec.scale),axis=0)/spec.scale
        assert error<=.500001/spec.scale,(error,spec.scale)
        assert float(np.max(np.abs(result-quantized)))<1e-12
        denied('approval_replay',roster[0],'approve',messages=messages,candidate=encode(candidate))
        denied('release_replay',roster[0],'release',messages=messages,candidate=encode(candidate),approvals=approvals)
        denied('duplicate_contribution',roster[0],'contribute')
        assert len(set(group.pids.values()))==n
        report=dict(status='functional_and_two_attack_regressions_passed',protocol=spec.protocol,backend='Ristretto255 additive ElGamal + PoK/DLEQ + Bulletproofs',
            participants=n,independent_processes=n,length=length,scale=spec.scale,input_bound=spec.bound,
            max_absolute_mean_error=error,quantized_control_max_error=float(np.max(np.abs(result-quantized))),
            negative_checks=checks,phases=phases,total_seconds=time.monotonic()-start,
            rpc_json_request_bytes=group.request_bytes,rpc_json_response_bytes=group.response_bytes,rpc_requests=group.request_count,
            traffic_scope='Includes setup, proofs, positive and rejected RPCs; excludes TLS/HTTP framing. Phase timings are diagnostic, not training benchmarks.',
            mtls=True,coordinator_knows_synthetic_fixture_inputs=True,test_only_signing_oracle_enabled=True,
            independent_host_isolation_verified=False,training_integration_complete=False,independent_security_audit=False,
            limits='Known two attacks rejected; no poisoning resistance, DP, dropout recovery or general active-MPC security claim.')
    assert not any(p.is_alive() for p in group.processes)
    report['workers_stopped']=True
    root=Path(__file__).resolve().parents[1]
    files=sorted(p for p in (root/'src/secure_protocol_v6').glob('*.py') if p.name!='training_adapter.py')+sorted((root/'src/secure_protocol_v5').glob('*.py'))+sorted((root/'src/secure_protocol_v4').glob('*.py'))+[Path(__file__).resolve(),root/'tests/test_secure_protocol_v6.py',root/'native/dfl_range/Cargo.toml',root/'native/dfl_range/Cargo.lock',root/'native/dfl_range/src/lib.rs']
    report['source_sha256']={p.relative_to(root).as_posix():hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest() for p in files}
    report['source_hash_convention']='UTF8 text normalized to LF'
    report['range_proofs_required']=True;report['range_backend']=rp.info()
    report['runtime']=dict(python=platform.python_version(),platform=platform.platform(),packages={name:importlib.metadata.version(name) for name in ['rbcl','cryptography','numpy']})
    output.parent.mkdir(parents=True,exist_ok=True);temp=output.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');os.replace(temp,output)
    print(json.dumps(report),flush=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--participants',type=int,default=3);parser.add_argument('--length',type=int,default=2570);parser.add_argument('--parallelism',type=int,default=8);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    run(args.participants,args.length,args.parallelism,args.output)
