"""Private decentralized client: opaque neighbor sessions, aggregate metrics only."""
import copy,json,math,os,sys
from pathlib import Path
import numpy as np
import torch
from secure_protocol_v4.core import Identity,RoundSpec,canonical,digest,encode,decode,verify,complete,Rejected
from cryptography.hazmat.primitives.asymmetric import ed25519,x25519
from secure_protocol_v6.rangeproof import info
from secure_protocol_v6.training_adapter import state_hash
from independent_clients.common import atomic_json
from .groups import groups
from .session import Session
from . import training
from .protocol import control,signed_subset,local_counters

class Service:
    operations={'status':set(),'train':{'round','epoch'},'enroll':{'messages'},'begin_group':{'group'},
        'act':{'group','phase','index'},'emit':{'group','phase','index','recipient'},
        'ingest':{'group','phase','index','owner','envelope'},'group_ready':{'group'},
        'group_accept':{'group','receipts'},'prepare_report':{'kind'},'accept_report':{'kind'},
        'round_ready':set(),'commit':{'receipts'}}
    def __init__(self,config,*,isolation):
        self.config=config;self.root=Path(config['private_dir']);self.job=config['job'];self.name=config['name'];self.isolation=isolation
        content={k:v for k,v in self.job.items() if k!='job_id'}
        if digest(canonical(content))!=self.job['job_id']:raise Rejected('job hash mismatch')
        from .runtime import source_hash
        if self.job['source_hash']!=source_hash() or info()['binary_sha256']!=self.job['native_binary_sha256']:raise Rejected('source/backend mismatch')
        self.identity=Identity(self.name);secret=json.loads((self.root/'identity.json').read_text())
        self.identity.signing=ed25519.Ed25519PrivateKey.from_private_bytes(decode(secret['signing']))
        self.identity.exchange=x25519.X25519PrivateKey.from_private_bytes(decode(secret['exchange']))
        if self.identity.registration()!=self.job['enrollment'][self.name]:raise Rejected('identity mismatch')
        self.saved=training.load(self.root/'checkpoint.pt');self.completed=self.saved['round'];self.ctx=None;self.exec_pending=False
        self.active=None;self.round_identity=None;self.round_roster=None;self.receipt=None;self.trained=None;self.pending=None;self.metrics=None
        self.done=set();self.group_hashes={};self.target_hashes={};self.group_defs={g['id']:g for g in self.job['groups']}
        self.request_path=self.root/'round.json'
        if self.request_path.exists():
            request=json.loads(self.request_path.read_text())
            if request['round']<=self.completed:self.request_path.unlink()
            elif (self.root/'pending.pt').exists():
                self.pending=training.load(self.root/'pending.pt');self.active=request;self.receipt=self.pending['ready'];self.metrics=self.pending['metrics']
            elif request['phase']=='crypto':raise Rejected('interrupted crypto requires operator recovery; no fresh release')
            elif (self.root/'trained.pt').exists():
                self.active=request;self.load_trained()

    def spec(self):return control(self.job,self.active['round'],self.active['epoch'])
    def load_trained(self):
        trained=training.load(self.root/'trained.pt')
        if trained['round']!=self.active['round'] or trained['base_hash']!=self.active['base']:raise Rejected('trained-state mismatch')
        self.trained=trained;self.round_identity=Identity(self.name);self.round_identity.signing=self.identity.signing
        self.active['phase']='trained';atomic_json(self.request_path,self.active)
        self.ready=self.identity.sign(self.spec(),'trained',dict(round=self.active['round'],base=self.active['base'],exchange=self.round_identity.registration()['exchange']))

    def status(self):
        return dict(name=self.name,job_id=self.job['job_id'],completed_round=self.completed,
            phase='pending_commit' if self.pending else self.active['phase'] if self.active else 'idle',
            ready=getattr(self,'ready',None),state_hash=state_hash(self.saved['state']),pid=os.getpid(),isolation=self.isolation,
            training_execution=self.trained.get('execution') if self.trained else None)

    def rpc(self,op,args):
        if op not in self.operations or not isinstance(args,dict) or set(args)!=self.operations[op]:raise Rejected('unsupported operation/arguments')
        if op=='status':return self.status()
        if op=='commit':return self.commit(args['receipts'])
        if self.pending:raise Rejected('pending commit first')
        if op=='train':
            number=args['round'];epoch=args['epoch']
            if type(number)!=int or number!=self.completed+1 or number>self.job['config']['rounds'] or not isinstance(epoch,str) or len(epoch)!=32 or any(c not in '0123456789abcdef' for c in epoch):raise Rejected('invalid round')
            if self.active:
                if self.active['round']==number and self.active['epoch']==epoch:return dict(accepted=True)
                raise Rejected('conflicting active epoch')
            self.active=dict(round=number,epoch=epoch,base=state_hash(self.saved['state']),phase='requested')
            atomic_json(self.request_path,self.active)
            if self.job['config']['training_device']=='cuda':self.exec_pending=True
            else:training.train(self.config,self.active);self.load_trained()
            return dict(accepted=True)
        if not self.active or self.trained is None:raise Rejected('client not trained')
        if op=='enroll':
            if self.round_roster is not None or self.ready not in args['messages']:raise Rejected('repeated/changed own enrollment')
            items=complete(args['messages'],self.spec(),'trained',self.job['enrollment']);rr={}
            for name,payload in items.items():
                if set(payload)!={'round','base','exchange'} or payload['round']!=self.active['round'] or len(decode(payload['exchange']))!=32:raise Rejected('bad round enrollment')
                rr[name]=dict(self.job['enrollment'][name],exchange=payload['exchange'])
            self.round_roster=rr;self.enrollment_messages=copy.deepcopy(args['messages']);self.active['phase']='crypto';atomic_json(self.request_path,self.active)
            return dict(enrollment_hash=digest(canonical(rr)))
        if self.round_roster is None:raise Rejected('round not enrolled')
        group=args.get('group')
        if op=='begin_group':
            if self.ctx is not None or group in self.done or group not in self.group_defs:raise Rejected('invalid/repeated group')
            definition=self.group_defs[group]
            if self.name not in definition['roster']:raise Rejected('not group member')
            self.make_session(definition,self.trained['state']);return dict(length=self.ctx.spec.length,split=self.ctx.split)
        if op=='prepare_report':return self.prepare_report(args['kind'])
        if op=='accept_report':return self.accept_report(args['kind'])
        if op=='round_ready':return self.round_ready()
        if self.ctx is None or group!=self.ctx.group['id']:raise Rejected('no matching group')
        if op=='act':return self.ctx.act(args['phase'],args['index'])
        if op=='emit':return self.ctx.emit(args['phase'],args['index'],args['recipient'])
        if op=='ingest':return self.ctx.ingest(args['phase'],args['index'],args['owner'],args['envelope'])
        if op=='group_ready':
            if self.ctx.result is None:raise Rejected('group incomplete')
            if group not in ('report_metrics','report_test'):
                maximum=max(local_counters(self.job,self.active['round'])[n] for n in self.ctx.group['roster'])
                for name,value in self.ctx.result.items():
                    if not value.is_floating_point():value.fill_(maximum)
            h=state_hash(self.ctx.result)
            return self.identity.sign(self.spec(),'group_ready',dict(group=group,state_hash=h))
        if op=='group_accept':
            if self.ctx.result is None:raise Rejected('group incomplete')
            items=signed_subset(args['receipts'],self.spec(),'group_ready',self.job['enrollment'],self.ctx.group['roster'])
            h=state_hash(self.ctx.result)
            if any(p!=dict(group=group,state_hash=h) for p in items.values()):raise Rejected('group consensus mismatch')
            if self.name in self.ctx.group['targets']:self.mixed={n:v.clone() for n,v in self.ctx.result.items()}
            for name in self.ctx.group['targets']:self.target_hashes[name]=h
            self.group_hashes[group]=h;self.done.add(group);self.ctx.close();self.ctx=None
            return True
        raise Rejected('invalid phase')

    def make_session(self,definition,state,scale=None):
        schema=digest(canonical(dict(job=self.job['job_id'],group=definition,enrollment=self.enrollment_messages)))
        folder=self.root/f"round_{self.active['round']}";folder.mkdir(exist_ok=True)
        cfg=self.job['config'];self.ctx=Session(self.name,self.round_identity,self.round_roster,definition,state,
            run=self.job['job_id'],epoch=self.active['epoch'],number=self.active['round'],model=cfg['model'],schema=schema,folder=folder,
            scale=scale or cfg['scale'],head_bound=cfg['head_bound'],bound=cfg['backbone_bound'])

    def prepare_report(self,kind):
        expected={g['id'] for g in self.job['groups'] if self.name in g['roster']}
        if self.ctx is not None or not expected<=self.done or not hasattr(self,'mixed'):raise Rejected('neighbor groups incomplete')
        cfg=self.job['config'];r=self.active['round'];scheduled=r%cfg['validation_every']==0 or r==cfg['rounds']
        if kind=='metrics':
            if hasattr(self,'mean_metrics'):raise Rejected('metrics already accepted')
            vals=training.evaluate(self.mixed,self.config['validation_path'],self.job) if scheduled else [0.,0.]
            values=[self.trained['train_loss'],*vals]
        elif kind=='test':
            if cfg['test_policy']=='never' or r!=cfg['rounds'] or not hasattr(self,'mean_metrics') or hasattr(self,'mean_test'):raise Rejected('test not permitted')
            best=training.load(self.root/'best.pt')['state']
            values=training.evaluate(self.mixed,self.config['test_path'],self.job)+training.evaluate(best,self.config['test_path'],self.job)
        else:raise Rejected('invalid report')
        definition=dict(id='report_'+kind,roster=self.job['roster'],targets=[],mode='pairwise_masking')
        self.make_session(definition,{'metric':torch.tensor(values,dtype=torch.float64)},scale=10**9)
        return dict(length=len(values),split=False)

    def accept_report(self,kind):
        if self.ctx is None or self.ctx.group['id']!='report_'+kind or self.ctx.result is None:raise Rejected('report incomplete')
        value=self.ctx.result['metric'].numpy().tolist()
        # Group releases already verify all members. No private model output leaves.
        self.ctx.close();self.ctx=None
        if kind=='metrics':
            self.mean_metrics=value
            cfg=self.job['config'];r=self.active['round'];scheduled=r%cfg['validation_every']==0 or r==cfg['rounds']
            score=self.saved.get('best_score',-1.)
            if scheduled and value[1]>score:
                training.save(self.root/'best.pt',dict(round=r,state=self.mixed,validation_accuracy=value[1]));self.best_score=value[1];self.best_round=r
            else:self.best_score=score;self.best_round=self.saved.get('best_round',0)
        elif kind=='test':self.mean_test=value
        else:raise Rejected('invalid report kind')
        return dict(values=value)

    def round_ready(self):
        r=self.active['round'];cfg=self.job['config']
        if not hasattr(self,'mean_metrics') or (r==cfg['rounds'] and cfg['test_policy']!='never' and not hasattr(self,'mean_test')):raise Rejected('metrics not complete')
        metrics=dict(train_loss=self.mean_metrics[0],validation_accuracy=100*self.mean_metrics[1] if r%cfg['validation_every']==0 or r==cfg['rounds'] else None,
            validation_loss=self.mean_metrics[2] if r%cfg['validation_every']==0 or r==cfg['rounds'] else None,best_round=self.best_round,best_validation_accuracy=100*self.best_score,
            test_final_accuracy=100*self.mean_test[0] if hasattr(self,'mean_test') else None,test_final_loss=self.mean_test[1] if hasattr(self,'mean_test') else None,
            test_best_accuracy=100*self.mean_test[2] if hasattr(self,'mean_test') else None,test_best_loss=self.mean_test[3] if hasattr(self,'mean_test') else None)
        payload=dict(round=r,state_hash=state_hash(self.mixed),metrics=metrics)
        ready=self.identity.sign(self.spec(),'round_ready',payload)
        self.pending=dict(round=r,state=self.mixed,optimizer=self.trained['optimizer'],rng=self.trained['rng'],best_score=self.best_score,best_round=self.best_round,ready=ready,metrics=metrics)
        training.save(self.root/'pending.pt',self.pending);self.receipt=ready;self.metrics=metrics
        return ready

    def commit(self,messages):
        if self.pending is None:
            if self.saved.get('commit_hash')==digest(canonical(messages)):return self.saved['commit_response']
            raise Rejected('no pending state')
        items=complete(messages,self.spec(),'round_ready',self.job['enrollment']);mine=items[self.name]
        if self.receipt not in messages or mine['state_hash']!=state_hash(self.pending['state']) or any(p['metrics']!=self.metrics or p['round']!=self.pending['round'] for p in items.values()):raise Rejected('round consensus failed')
        for target,h in self.target_hashes.items():
            if items[target]['state_hash']!=h:raise Rejected('neighbor result differs from consensus')
        response=dict(name=self.name,round=self.pending['round'],state_hash=mine['state_hash'])
        self.saved={k:v for k,v in self.pending.items() if k not in ('ready','metrics')};self.saved.update(commit_hash=digest(canonical(messages)),commit_response=response)
        training.save(self.root/'checkpoint.pt',self.saved);self.completed=self.saved['round']
        for filename in ['pending.pt','trained.pt','round.json']:(self.root/filename).unlink(missing_ok=True)
        self.pending=None;self.active=None;self.trained=None;self.ctx=None;self.done=set();self.group_hashes={};self.target_hashes={};self.round_roster=None
        for field in ('mixed','ready','mean_metrics','mean_test','enrollment_messages'):
            if hasattr(self,field):delattr(self,field)
        return response

    def after_reply(self):
        if self.exec_pending:
            self.exec_pending=False
            from .runtime import replace_process
            try:replace_process(self.config,'gpu_worker')
            except OSError:
                self.active['phase']='failed_worker_start';atomic_json(self.request_path,self.active)
                raise
