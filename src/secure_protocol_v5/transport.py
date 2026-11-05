"""Bounded loopback mTLS process harness; trusted setup/fixtures, not host isolation."""
import http.client,json,multiprocessing as mp,os,ssl,tempfile,socket,threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from secure_protocol_v4.transport import BoundedHTTPServer,certificates,common_name,strict_object,reject_constant,MAX_BODY,IO_TIMEOUT
from secure_protocol_v4.core import Rejected,complete,encode,decode,aggregate_tag
from .node import Node,RoundSpec
from . import crypto as c

DEADLINE=300
def worker(pipe,name,spec_data,folder,values,testing):
    node=Node(name,RoundSpec(**spec_data),Path(folder)/(name+'.sqlite'))
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(IO_TIMEOUT)
            def expire():
                try:self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            self.timer=threading.Timer(DEADLINE,expire);self.timer.daemon=True;self.timer.start()
        def finish(self):self.timer.cancel();super().finish()
        def log_message(self,*args):pass
        def do_POST(self):
            try:
                if self.path!='/rpc' or common_name(self.connection.getpeercert())!=node.spec.target:raise Rejected('unauthorized identity/path')
                lengths=self.headers.get_all('Content-Length',[])
                if len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdecimal() or len(lengths[0])>10:raise Rejected('invalid length')
                if self.headers.get_all('Transfer-Encoding') or self.headers.get_all('Expect') or self.headers.get_all('Content-Type')!=['application/json']:raise Rejected('invalid framing')
                size=int(lengths[0])
                if not 0<size<=MAX_BODY:raise Rejected('body too large')
                body=self.rfile.read(size)
                if len(body)!=size:raise Rejected('incomplete body')
                request=json.loads(body,object_pairs_hook=strict_object,parse_constant=reject_constant)
                if not isinstance(request,dict) or set(request)!={'op','args'}:raise Rejected('invalid envelope')
                op=request['op'];args=request['args']
                expected={'keygen':set(),'set_keys':{'messages'},'contribute':set(),'approve':{'messages','candidate'},'release':{'messages','candidate','approvals'}}
                if testing:expected.update(test_forge={'phase','payload'},test_single_share=set())
                if not isinstance(op,str) or op not in expected or not isinstance(args,dict) or set(args)!=expected[op]:raise Rejected('unsupported operation/args')
                if op=='keygen':result=node.keygen()
                elif op=='set_keys':result=node.set_keys(args['messages'])
                elif op=='contribute':result=node.contribution(values)
                elif op=='approve':result=node.approve(args['messages'],decode(args['candidate']))
                elif op=='release':result=node.release(args['messages'],decode(args['candidate']),args['approvals'])
                elif op=='test_forge':result=node.identity.sign(node.spec,args['phase'],args['payload'])
                else:
                    import numpy as np
                    raw=decode(node.own['body']['payload']['data']);_,parts=next(c.chunks(raw,192,node.spec.length))
                    result=c.sub(parts[1],c.mul(node.secret,parts[0]))==c.base(c.scalar(np.rint(values[0]*node.spec.scale)))
                payload=json.dumps(dict(ok=True,result=result)).encode();status=200
            except (Rejected,ValueError,TypeError,KeyError,TimeoutError):payload=b'{"ok":false,"error":"request rejected"}';status=400
            except Exception:payload=b'{"ok":false,"error":"internal error; abort round"}';status=500
            self.close_connection=True;self.send_response(status);self.send_header('Connection','close');self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_3
    tls.load_cert_chain(str(Path(folder)/(name+'.pem')),str(Path(folder)/(name+'.key')))
    tls.load_verify_locations(str(Path(folder)/'ca.pem'));tls.verify_mode=ssl.CERT_REQUIRED
    server=BoundedHTTPServer(('127.0.0.1',0),Handler,tls)
    pipe.send(dict(registration=node.registration(),port=server.server_port,pid=os.getpid()))
    node.pin(pipe.recv());pipe.send('ready');pipe.close();server.serve_forever()

class Group:
    """Coordinator knows fixture inputs; private node keys stay in worker processes."""
    def __init__(self,spec,values,testing=False,parallelism=8):
        self.spec=spec;self.parallelism=min(parallelism,len(spec.roster));self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.processes=[];self.connections={};self.roster={};self.addresses={};self.pids={};self.keys=None
        self.request_bytes=0;self.response_bytes=0;self.request_count=0;self.counter_lock=threading.Lock();pipes=[]
        try:
            if set(values)!=set(spec.roster):raise Rejected('fixture roster mismatch')
            certificates(self.folder,spec.roster);ctx=mp.get_context('spawn')
            for name in spec.roster:
                parent,child=ctx.Pipe();process=ctx.Process(target=worker,args=(child,name,spec.body(),str(self.folder),values[name],testing))
                process.start();child.close();self.processes.append(process);pipes.append(parent)
                if not parent.poll(60):raise Rejected('startup timeout')
                item=parent.recv();self.roster[name]=item['registration'];self.addresses[name]=item['port'];self.pids[name]=item['pid']
            for pipe in pipes:pipe.send(self.roster)
            for pipe in pipes:
                if not pipe.poll(30) or pipe.recv()!='ready':raise Rejected('enrollment timeout')
            tls=ssl.create_default_context(cafile=str(self.folder/'ca.pem'));tls.minimum_version=ssl.TLSVersion.TLSv1_3
            tls.load_cert_chain(str(self.folder/(spec.target+'.pem')),str(self.folder/(spec.target+'.key')))
            self.connections={name:http.client.HTTPSConnection('localhost',port,context=tls,timeout=DEADLINE+10) for name,port in self.addresses.items()}
        except BaseException:self.close();raise
        finally:
            for pipe in pipes:pipe.close()
    def call(self,name,op,**args):
        conn=self.connections[name];body=json.dumps(dict(op=op,args=args),allow_nan=False).encode()
        if len(body)>MAX_BODY:raise Rejected('request too large')
        if conn.sock is None:conn.connect()
        if common_name(conn.sock.getpeercert())!=name:conn.close();raise Rejected('wrong server identity')
        with self.counter_lock:self.request_bytes+=len(body);self.request_count+=1
        conn.request('POST','/rpc',body,{'Content-Type':'application/json'});response=conn.getresponse();raw=response.read(MAX_BODY+1)
        if len(raw)>MAX_BODY:conn.close();raise Rejected('response too large')
        with self.counter_lock:self.response_bytes+=len(raw)
        data=json.loads(raw)
        if response.status!=200 or not data['ok']:raise Rejected(data.get('error','rejected'))
        return data['result']
    def parallel(self,op,**args):
        with ThreadPoolExecutor(max_workers=self.parallelism) as pool:
            return list(pool.map(lambda n:self.call(n,op,**args),self.spec.roster))
    def keygen(self):
        self.keys=self.parallel('keygen');return self.keys
    def set_keys(self,messages=None):
        messages=self.keys if messages is None else messages
        publics=self.parallel('set_keys',messages=messages)
        if len(set(publics))!=1:raise Rejected('joint public key disagreement')
        self.public=decode(publics[0]);return self.public
    def contributions(self):return self.parallel('contribute')
    def average(self,messages):
        items=complete(messages,self.spec,'contribution',self.roster)
        return c.aggregate([decode(items[n]['data']) for n in self.spec.roster],self.spec.length)
    def approvals(self,messages,candidate):return self.parallel('approve',messages=messages,candidate=encode(candidate))
    def releases(self,messages,candidate,approvals):return self.parallel('release',messages=messages,candidate=encode(candidate),approvals=approvals)
    def recover(self,messages,candidate,releases):
        items=complete(releases,self.spec,'release',self.roster);keys=complete(self.keys,self.spec,'keyshare',self.roster)
        tag=aggregate_tag(self.spec,messages,encode(candidate))
        def check(name):
            payload=items[name]
            if set(payload)!={'aggregate','data'} or payload['aggregate']!=tag:raise Rejected('release context mismatch')
            public=c.verify_key(bytes.fromhex(self.spec.tag),name,decode(keys[name]['data']))
            return c.verify_partial(decode(payload['data']),candidate,self.spec,public,tag,name)
        with ThreadPoolExecutor(max_workers=self.parallelism) as pool:columns=list(pool.map(check,self.spec.roster))
        decoder=c.BoundedLog(math_bound(self.spec));result=[]
        for i,(_,C) in c.chunks(candidate,64,self.spec.length):
            total=c.IDENTITY
            for column in columns:total=c.add(total,column[i])
            result.append(decoder.decode(c.sub(C,total))/(self.spec.scale*len(self.spec.roster)))
        return result
    def close(self):
        for conn in self.connections.values():conn.close()
        for process in self.processes:
            if process.is_alive():process.terminate()
            process.join(timeout=10)
        self.tmp.cleanup()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

def math_bound(spec):return int(__import__('math').ceil(spec.bound*spec.scale*len(spec.roster)+len(spec.roster)))
