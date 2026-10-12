import argparse
import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .store import Store, ROOT
from .model import Model


def main():
    p=argparse.ArgumentParser(description='A local Palimpsest notebook. No automatic model calls or uploads.')
    p.add_argument('--db',default=str(ROOT/'data/notebook.sqlite3'))
    sub=p.add_subparsers(dest='command',required=True)
    server=sub.add_parser('serve'); server.add_argument('--port',type=int,default=8766)
    server.add_argument('--base-url',default='http://127.0.0.1:11434')
    server.add_argument('--model',default='qwen2.5:7b-instruct-q4_K_M')
    server.add_argument('--protocol',choices=['ollama','chat-completions'],default='ollama')
    server.add_argument('--key-env')
    capture=sub.add_parser('capture'); capture.add_argument('body'); capture.add_argument('--kind',default='learner'); capture.add_argument('--author',default='learner')
    export=sub.add_parser('export'); export.add_argument('output'); export.add_argument('--attachments',action='store_true')
    restore=sub.add_parser('restore'); restore.add_argument('bundle')
    sub.add_parser('list')
    args=p.parse_args()
    if args.command=='serve':
        serve(args); return
    store=Store(args.db)
    try:
        if args.command=='capture': result=store.capture(args.body,args.kind,args.author)
        elif args.command=='list': result=store.entries()
        elif args.command=='restore': result=store.restore(json.loads(Path(args.bundle).read_text()))
        else:
            refs=[{'id':r['id'],'revision':r['revision']} for r in store.db.execute('SELECT id,revision FROM revisions')]
            result=store.export(refs,args.attachments)
            # A portable backup also carries state and events, separately from source imports.
            result['session_snapshot']=store.state(); result['event_history']=store.events(); result['investigations']=store.investigations()
            Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2))
            result={'written':args.output,'revisions':len(refs),'note':'Full private backup. Imports restore sources; session/events remain inspectable in this file.'}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally: store.close()


def serve(args):
    model=Model(args.base_url,args.model,args.protocol,args.key_env)
    token=secrets.token_urlsafe(32)
    previews={}; preview_lock=threading.Lock(); run_lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def send(self,status,data,ctype='application/json'):
            data=json.dumps(data,ensure_ascii=False).encode() if ctype=='application/json' else data.encode() if isinstance(data,str) else data
            self.send_response(status)
            self.send_header('Content-Type',ctype)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers(); self.wfile.write(data)

        def allowed(self,write=False):
            if self.headers.get('Host') not in {f'localhost:{args.port}',f'127.0.0.1:{args.port}'}:
                self.send(403,{'error':'Local host required'}); return False
            origin=self.headers.get('Origin')
            if origin and origin not in {f'http://localhost:{args.port}',f'http://127.0.0.1:{args.port}'}:
                self.send(403,{'error':'Same-origin request required'}); return False
            if self.headers.get('Sec-Fetch-Site')=='cross-site':
                self.send(403,{'error':'Cross-site access refused'}); return False
            if write and not secrets.compare_digest(self.headers.get('X-Palimpsest-Token',''),token):
                self.send(403,{'error':'Reload the local page before saving'}); return False
            return True

        def do_GET(self):
            if not self.allowed(): return
            path=urlsplit(self.path).path
            static={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
            if path in static:
                ctype={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[path]
                return self.send(200,(ROOT/'web'/static[path]).read_text(),ctype)
            store=Store(args.db)
            try:
                if path=='/api/state':
                    events=store.events()
                    finished={e['payload']['run_id'] for e in events if e['type']=='run-finished'}
                    self.send(200,{'session':store.state(),'entries':store.entries(),'events':events,'investigations':store.investigations(),
                        'outstanding_runs':[e['id'] for e in events if e['type']=='run-started' and e['id'] not in finished],
                        'model':model.config(),'token':token})
                elif path=='/api/health': self.send(200,{'application':'palimpsest','interface':'question-atlas'})
                elif path=='/api/landscape': self.send(200,json.loads((ROOT/'course/landscape.json').read_text()))
                else: self.send(404,{'error':'Not found'})
            finally: store.close()

        def do_POST(self):
            if not self.allowed(True): return
            store=Store(args.db)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=8_000_000: raise ValueError('Request size must be 1 byte to 8 MB')
                data=json.loads(self.rfile.read(length))
                path=urlsplit(self.path).path
                if path=='/api/capture':
                    investigation=data.pop('investigation_id',None)
                    if investigation and investigation not in {i['id'] for i in store.investigations()}:
                        raise ValueError('Unknown investigation')
                    result=store.capture(**data)
                    if investigation: store.link_entries(investigation,[{'id':result['id'],'revision':result['revision']}])
                elif path=='/api/investigation': result=store.open_investigation(**data)
                elif path=='/api/investigation/link': result=store.link_entries(**data)
                elif path=='/api/revision': result=store.get(data)
                elif path=='/api/session':
                    old=store.state()
                    if 'question' in data and 'mode' not in data and re.match(
                        r'^(?:please\s+)?(?:just\s+)?(?:tell me|explain|fix|implement|give me (?:the|a) (?:answer|worked example))\b',
                        data['question'].strip(),re.I):
                        data.update(mode='direct help',help_level='explicit request for direct assistance')
                    result=store.set_state(data)
                    if old['mode']!='direct help' and result['mode']=='direct help':
                        store.exception('C4','Current question: '+(result['question'] or 'direct assistance'),
                            'Learner chose direct help through mode control or explicit request','Return to another mode','active')
                    elif old['mode']=='direct help' and result['mode']!='direct help':
                        store.exception('C4','Prior direct-help session','Learner changed mode in local UI','Returned to '+result['mode'],'ended')
                elif path=='/api/context':
                    result=store.bundle(**data)
                    with preview_lock:
                        if len(previews)>=100: previews.pop(next(iter(previews)))
                        previews[result['id']]=result
                elif path=='/api/run':
                    with preview_lock:
                        bundle=previews.pop(data.get('context_id'),None)
                    if not bundle: raise ValueError('Preview the exact context before sending; previews expire after use or server restart')
                    if not run_lock.acquire(blocking=False): raise ValueError('A model request is already running; wait and preview again')
                    try:
                        result=model.run(store,bundle)
                        active=bundle.get('investigation_id')
                        if active and result.get('output_ref'):
                            store.link_entries(active,[result['output_ref']])
                    finally: run_lock.release()
                elif path=='/api/export': result=store.export(**data)
                elif path=='/api/restore': result=store.restore(data)
                elif path=='/api/compile': result=store.compile(**data); store.event('edition-draft',{'id':result['id'],'manifest':result['manifest']})
                elif path=='/api/gate/propose': result=store.propose_gate(**data)
                elif path=='/api/gate/respond': result=store.respond_gate(**data)
                else: return self.send(404,{'error':'Not found'})
                self.send(200,result)
            except (ValueError,TypeError,KeyError) as exc:
                self.send(400,{'error':str(exc)})
            except Exception:
                self.send(500,{'error':'Operation failed; no completion is claimed. Check the local data store.'})
            finally: store.close()
    httpd=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Palimpsest: http://127.0.0.1:{args.port} · {model.config()["route"]} · {args.model}',flush=True)
    try: httpd.serve_forever()
    except KeyboardInterrupt: pass
    finally: httpd.server_close()

if __name__=='__main__': main()
