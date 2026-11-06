"""Bounded mTLS independent-service transport, no process spawning or fixture data."""
import http.client
from http.server import BaseHTTPRequestHandler
import json
import socket
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from secure_protocol_v4.core import Rejected
from secure_protocol_v4.transport import BoundedHTTPServer,common_name,strict_object,reject_constant,MAX_BODY,IO_TIMEOUT

DEADLINE=1200


def serve(service,config):
    root=Path(config['private_dir'])
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
                if self.path!='/rpc' or common_name(self.connection.getpeercert())!='coordinator':raise Rejected('unauthorized path/identity')
                lengths=self.headers.get_all('Content-Length',[])
                if len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdecimal() or len(lengths[0])>10:raise Rejected('invalid content length')
                if self.headers.get_all('Transfer-Encoding') or self.headers.get_all('Expect') or self.headers.get_all('Content-Type')!=['application/json']:raise Rejected('invalid framing')
                size=int(lengths[0])
                if not 0<size<=MAX_BODY:raise Rejected('request too large')
                raw=self.rfile.read(size)
                if len(raw)!=size:raise Rejected('truncated request')
                request=json.loads(raw,object_pairs_hook=strict_object,parse_constant=reject_constant)
                if not isinstance(request,dict) or set(request)!={'op','args'} or not isinstance(request['op'],str):raise Rejected('invalid envelope')
                result=service.rpc(request['op'],request['args'])
                data=json.dumps(dict(ok=True,result=result),allow_nan=False).encode();status=200
            except (Rejected,ValueError,TypeError,KeyError,TimeoutError):
                data=b'{"ok":false,"error":"request rejected"}';status=400
            except Exception:
                data=b'{"ok":false,"error":"operation failed; operator recovery may be required"}';status=500
            self.close_connection=True;self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.send_header('Connection','close');self.end_headers();self.wfile.write(data)
            if hasattr(service,'after_reply'):
                self.wfile.flush();service.after_reply()
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_3
    tls.load_cert_chain(str(root/'tls.pem'),str(root/'tls.key'));tls.load_verify_locations(str(root/'ca.pem'));tls.verify_mode=ssl.CERT_REQUIRED
    server=BoundedHTTPServer((config.get('bind','127.0.0.1'),config['port']),Handler,tls)
    # Port supplied by the trusted deployment configuration, not a trainer command.
    print(json.dumps(dict(status='listening',name=service.name,port=server.server_port)),flush=True)
    server.serve_forever()


class RemoteClients:
    def __init__(self,config,parallelism=4,audit_mode='full'):
        if audit_mode not in ('full','aggregate'):raise ValueError('unsupported audit mode')
        root=Path(config['private_dir']);self.job=config['job'];self.parallelism=parallelism
        tls=ssl.create_default_context(cafile=str(root/'ca.pem'));tls.minimum_version=ssl.TLSVersion.TLSv1_3
        tls.load_cert_chain(str(root/'tls.pem'),str(root/'tls.key'))
        self.connections={name:http.client.HTTPSConnection(item['host'],item['port'],context=tls,timeout=DEADLINE+10) for name,item in config['endpoints'].items()}
        self.calls=[];self.audit_mode=audit_mode;self.audit_totals={};self.request_bytes=0;self.response_bytes=0;self.lock=threading.Lock()
    def call(self,name,op,**args):
        try:return self._call(name,op,**args)
        except (OSError,http.client.HTTPException):
            self.connections[name].close()
            raise
    def _call(self,name,op,**args):
        body=json.dumps(dict(op=op,args=args),allow_nan=False).encode()
        if len(body)>MAX_BODY:raise Rejected('request too large')
        conn=self.connections[name]
        if conn.sock is None:conn.connect()
        if not isinstance(conn.sock,ssl.SSLSocket):
            conn.close();raise ConnectionError('TLS connection not established')
        if common_name(conn.sock.getpeercert())!=name:
            conn.close();raise Rejected('wrong client TLS identity')
        conn.request('POST','/rpc',body,{'Content-Type':'application/json'})
        response=conn.getresponse();raw=response.read(MAX_BODY+1)
        if len(raw)>MAX_BODY:raise Rejected('response too large')
        message=json.loads(raw,object_pairs_hook=strict_object,parse_constant=reject_constant)
        if not isinstance(message,dict):raise Rejected('invalid response type')
        with self.lock:
            entry=dict(client=name,op=op,request_bytes=len(body),response_bytes=len(raw),status=response.status,ok=message.get('ok') is True)
            if self.audit_mode=='full' or len(self.calls)<100:self.calls.append(entry)
            if self.audit_mode=='aggregate':
                key=(name,op,response.status,entry['ok']);total=self.audit_totals.setdefault(key,dict(client=name,op=op,status=response.status,ok=entry['ok'],calls=0,request_bytes=0,response_bytes=0))
                total['calls']+=1;total['request_bytes']+=len(body);total['response_bytes']+=len(raw)
            self.request_bytes+=len(body);self.response_bytes+=len(raw)
        if response.status!=200 or message.get('ok') is not True:raise Rejected('client rejected operation')
        if set(message)!={'ok','result'}:raise Rejected('invalid response envelope')
        return message['result']
    def parallel(self,op,**args):
        with ThreadPoolExecutor(max_workers=self.parallelism) as pool:
            return list(pool.map(lambda n:self.call(n,op,**args),self.job['roster']))
    def close(self):
        for connection in self.connections.values():connection.close()


class Segment:
    def __init__(self,remote,prefix,spec):
        self.remote=remote;self.prefix=prefix;self.spec=spec;self.roster=remote.job['enrollment'];self.parallelism=remote.parallelism
    def parallel(self,op,**args):return self.remote.parallel(self.prefix+'_'+op,**args)
