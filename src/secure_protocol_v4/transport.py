"""Loopback mTLS node processes. Trusted enrollment; private protocol keys stay in workers."""
import datetime as dt
import http.client
from http.server import HTTPServer,BaseHTTPRequestHandler
import json
import multiprocessing as mp
import os
from pathlib import Path
import ssl
import tempfile
import socket
import threading
from cryptography import x509
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes,serialization
from .core import RoundSpec,Rejected,decode,encode,complete,aggregate_tag
from .node import Node
from . import pairwise

MAX_BODY=64*1024*1024
IO_TIMEOUT=3.0
REQUEST_DEADLINE=30.0

class BoundedHTTPServer(HTTPServer):
    """Serial state machine with bounded TLS handshake and connection lifetime.

    Loopback experiment transport only, not an Internet-facing production server.
    """
    def __init__(self,address,handler,tls):
        self.tls=tls
        super().__init__(address,handler)
    def get_request(self):
        raw,address=self.socket.accept();raw.settimeout(IO_TIMEOUT)
        try:return self.tls.wrap_socket(raw,server_side=True),address
        except BaseException:raw.close();raise
    def handle_error(self,request,client_address):pass

def strict_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise Rejected('duplicate JSON key')
        result[key]=value
    return result

def reject_constant(value):raise Rejected('non-finite JSON value')
def certificates(folder,names,validity_days=1):
    root=Path(folder);os.chmod(root,0o700)
    key=ec.generate_private_key(ec.SECP256R1());now=dt.datetime.now(dt.timezone.utc)
    ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'DFL v4 ephemeral experiment CA')])
    def builder(subject,issuer,pub):
        return x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(pub).serial_number(x509.random_serial_number()).not_valid_before(now-dt.timedelta(minutes=5)).not_valid_after(now+dt.timedelta(days=validity_days))
    ca=builder(ca_name,ca_name,key.public_key()).add_extension(x509.BasicConstraints(ca=True,path_length=0),True).sign(key,hashes.SHA256())
    (root/'ca.pem').write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    for name in names:
        private=ec.generate_private_key(ec.SECP256R1())
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,name)])
        cert=builder(subject,ca_name,private.public_key()).add_extension(x509.BasicConstraints(ca=False,path_length=None),True).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),False).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH,ExtendedKeyUsageOID.CLIENT_AUTH]),False).sign(key,hashes.SHA256())
        (root/(name+'.pem')).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        p=root/(name+'.key');p.write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));os.chmod(p,0o600)
    # CA private key is never written; certificate provisioning is trusted setup.
def common_name(cert):
    return next(v for fields in cert['subject'] for k,v in fields if k=='commonName')

def worker(pipe,name,spec_data,context,folder,values,testing):
    os.environ['OMP_NUM_THREADS']='1'
    spec=RoundSpec(**spec_data);node=Node(name,spec,Path(folder)/(name+'.sqlite'),context)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(IO_TIMEOUT)
            def expire():
                try:self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            self.deadline=threading.Timer(REQUEST_DEADLINE,expire);self.deadline.daemon=True;self.deadline.start()
        def finish(self):
            self.deadline.cancel()
            super().finish()
        def log_message(self,*args):pass
        def do_POST(self):
            try:
                if self.path!='/rpc' or common_name(self.connection.getpeercert())!=spec.target:
                    raise Rejected('unauthorized transport identity/path')
                lengths=self.headers.get_all('Content-Length',[])
                if len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdecimal() or len(lengths[0])>10:
                    raise Rejected('invalid content length')
                if self.headers.get_all('Transfer-Encoding') or self.headers.get_all('Expect'):
                    raise Rejected('unsupported HTTP framing')
                if self.headers.get_all('Content-Type')!=['application/json']:raise Rejected('expected JSON content type')
                size=int(lengths[0])
                if not 0<size<=MAX_BODY:raise Rejected('invalid body size')
                body=self.rfile.read(size)
                if len(body)!=size:raise Rejected('incomplete request body')
                req=json.loads(body,object_pairs_hook=strict_object,parse_constant=reject_constant)
                if not isinstance(req,dict) or not {'op'}<=set(req)<={'op','args'} or not isinstance(req['op'],str):
                    raise Rejected('invalid request envelope')
                op=req['op'];a=req.get('args',{})
                expected={'keygen':{'previous','chain'},'set_key':{'chain'},'contribute':set(),'approve':{'messages','candidate'},'release':{'messages','candidate','approvals'}}
                if testing:expected['probe']=set()
                if op not in expected or not isinstance(a,dict) or set(a)!=expected[op]:raise Rejected('unsupported operation/arguments')
                if op=='keygen':res=node.keygen(decode(a['previous']) if a['previous'] else None,a['chain'])
                elif op=='set_key':node.set_key(a['chain']);res=True
                elif op=='contribute':res=node.contribution(values)
                elif op=='approve':res=node.approve(a['messages'],decode(a['candidate']))
                elif op=='release':res=node.release(a['messages'],decode(a['candidate']),a['approvals'])
                elif op=='probe' and testing:
                    try:
                        import numpy as np
                        data=decode(node.own['body']['payload']['data'])
                        p=node.crypto.cc.Decrypt(node.secret,node.crypto.ciphertext(data));p.SetLength(spec.length)
                        res=bool(np.allclose(np.asarray(p.GetPackedValue())/node.crypto.SCALE,values,atol=1e-4,rtol=0))
                    except Exception:res=False
                else:raise Rejected('unsupported operation')
                data=json.dumps(dict(ok=True,result=res)).encode();self.send_response(200)
            except (Rejected,ValueError,TypeError,KeyError,TimeoutError):
                data=b'{"ok":false,"error":"request rejected"}';self.send_response(400)
            except Exception:
                # Native/backend exception text can include paths or other local details.
                data=b'{"ok":false,"error":"internal operation failed; abort round"}';self.send_response(500)
            self.close_connection=True
            self.send_header('Connection','close');self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_3
    tls.load_cert_chain(str(Path(folder)/(name+'.pem')),str(Path(folder)/(name+'.key')))
    tls.load_verify_locations(str(Path(folder)/'ca.pem'));tls.verify_mode=ssl.CERT_REQUIRED
    server=BoundedHTTPServer(('127.0.0.1',0),Handler,tls)
    pipe.send(dict(registration=node.registration(),port=server.server_port,pid=os.getpid()))
    node.pin(pipe.recv());pipe.send('ready');pipe.close();server.serve_forever()

class Group:
    """Trusted-host test harness: coordinator already knows every fixture input.

    This is NOT an untrusted-aggregator deployment or a local-data client service.
    It contains no Ed25519/X25519 private node keys or BFV secret shares.
    Each group's round policy is fixed at process start, not chosen via RPC.
    """
    def __init__(self,spec,values,folder=None,testing=False):
        self.spec=spec;self.tmp=tempfile.TemporaryDirectory() if folder is None else None
        self.folder=Path(folder or self.tmp.name);self.folder.mkdir(parents=True,exist_ok=True)
        self.processes=[];self.connections={};self.roster={};self.addresses={};self.pids={}
        self.request_bytes=0;self.response_bytes=0;self.request_count=0
        self.crypto=None;pipes=[]
        try:
            if spec.kind=='he_bfv':
                from .openfhe_backend import MultipartyBFV
                self.crypto=MultipartyBFV(parties=len(spec.roster));context=self.crypto.context()
            else:context=None
            certificates(self.folder,spec.roster)
            if set(values)!=set(spec.roster):raise Rejected('fixture roster mismatch')
            ctx=mp.get_context('spawn')
            for name in spec.roster:
                parent,child=ctx.Pipe();p=ctx.Process(target=worker,args=(child,name,spec.body(),context,str(self.folder),values[name],testing))
                p.start();child.close();self.processes.append(p);pipes.append(parent)
                if not parent.poll(90):raise RuntimeError('node startup timeout')
                item=parent.recv();self.roster[name]=item['registration'];self.addresses[name]=item['port'];self.pids[name]=item['pid']
            for pipe in pipes:pipe.send(self.roster)
            for pipe in pipes:
                if not pipe.poll(30) or pipe.recv()!='ready':raise RuntimeError('enrollment timeout')
                pipe.close()
            tls=ssl.create_default_context(cafile=str(self.folder/'ca.pem'));tls.minimum_version=ssl.TLSVersion.TLSv1_3
            tls.load_cert_chain(str(self.folder/(spec.target+'.pem')),str(self.folder/(spec.target+'.key')))
            for name,port in self.addresses.items():
                conn=http.client.HTTPSConnection('localhost',port,context=tls,timeout=REQUEST_DEADLINE+5)
                self.connections[name]=conn
        except BaseException:self.close();raise
        finally:
            for pipe in pipes:pipe.close()
    def call(self,name,op,**args):
        c=self.connections[name]
        if c.sock is None:c.connect()
        if common_name(c.sock.getpeercert())!=name:raise Rejected('wrong server identity')
        body=json.dumps(dict(op=op,args=args),allow_nan=False).encode()
        if len(body)>MAX_BODY:raise Rejected('request exceeds transport limit')
        self.request_bytes+=len(body);self.request_count+=1
        c.request('POST','/rpc',body,{'Content-Type':'application/json'})
        response=c.getresponse();raw=response.read(MAX_BODY+1)
        if len(raw)>MAX_BODY:c.close();raise Rejected('response exceeds transport limit')
        self.response_bytes+=len(raw);data=json.loads(raw)
        if response.status!=200 or not data['ok']:raise Rejected(data.get('error','request rejected'))
        return data['result']
    def keygen(self):
        chain=[];previous=None
        for name in self.spec.roster:
            msg=self.call(name,'keygen',previous=previous,chain=chain);chain.append(msg);previous=msg['body']['payload']['key']
        for name in self.spec.roster:self.call(name,'set_key',chain=chain)
    def contributions(self):return [self.call(name,'contribute') for name in self.spec.roster]
    def average(self,messages):
        items=complete(messages,self.spec,'contribution',self.roster)
        data=[decode(items[k]['data']) for k in self.spec.roster]
        return self.crypto.average(data,len(data)) if self.crypto else pairwise.sum_vectors(data,self.spec)
    def finish(self,messages,candidate):
        approvals=[self.call(n,'approve',messages=messages,candidate=encode(candidate)) for n in self.spec.roster]
        self.last_approvals=approvals
        releases=[self.call(n,'release',messages=messages,candidate=encode(candidate),approvals=approvals) for n in self.spec.roster]
        items=complete(releases,self.spec,'release',self.roster);tag=aggregate_tag(self.spec,messages,encode(candidate))
        if any(p['aggregate']!=tag for p in items.values()):raise Rejected('wrong release binding')
        return self.crypto.fusion([decode(items[n]['data']) for n in self.spec.roster],self.spec) if self.crypto else pairwise.recover(candidate,self.spec)
    def close(self):
        for conn in self.connections.values():conn.close()
        for process in self.processes:
            if process.is_alive():process.terminate()
            process.join(timeout=10)
        if self.tmp:self.tmp.cleanup()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
