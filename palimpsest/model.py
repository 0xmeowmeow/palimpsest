import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .store import now

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Provider redirect refused')

class Model:
    def __init__(self, base='http://127.0.0.1:11434', model='qwen2.5:7b-instruct-q4_K_M', protocol='ollama', key_env=None, timeout=120):
        parsed=urllib.parse.urlsplit(base)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use a provider base URL without credentials, query or fragment')
        if parsed.scheme!='https' and parsed.hostname not in {'localhost','127.0.0.1','::1'}:
            raise ValueError('Remote providers require HTTPS')
        if protocol not in {'ollama','chat-completions'}:
            raise ValueError('Unknown protocol')
        self.base=base.rstrip('/'); self.model=model; self.protocol=protocol; self.key_env=key_env; self.timeout=timeout

    def config(self):
        return {'base_url':self.base,'model':self.model,'protocol':self.protocol,
                'temperature':0,'max_output_tokens':512,'timeout_seconds':self.timeout,
                'route':'local' if urllib.parse.urlsplit(self.base).hostname in {'localhost','127.0.0.1','::1'} else 'remote',
                'context_limit':'requested 8192 tokens for Ollama; provider acceptance must be inspected'}

    def run(self, store, bundle):
        started=now(); start=time.monotonic()
        config=self.config()
        event=store.event('run-started',{'config':config,'context':bundle,'started_at':started})
        payload={'model':self.model,'messages':bundle['messages'],'stream':False}
        if self.protocol=='ollama':
            payload['options']={'temperature':0,'num_predict':512,'num_ctx':8192}
            payload['keep_alive']='2m'
            endpoint='/api/chat'
        else:
            payload.update(temperature=0,max_tokens=512)
            endpoint='/chat/completions'
        headers={'Content-Type':'application/json'}
        try:
            if self.key_env:
                key=os.environ.get(self.key_env)
                if not key:
                    raise ValueError('Configured credential environment variable is unset')
                headers['Authorization']='Bearer '+key
            request=urllib.request.Request(self.base+endpoint,json.dumps(payload).encode(),headers)
            with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(request,timeout=self.timeout) as response:
                raw=response.read(8_000_001)
            if len(raw)>8_000_000:
                raise ValueError('Response size limit exceeded')
            result=json.loads(raw)
            if self.protocol=='ollama':
                answer=result['message']['content']
                metrics={k:result.get(k) for k in ['prompt_eval_count','eval_count','total_duration','load_duration','done','done_reason']}
            else:
                answer=result['choices'][0]['message']['content']
                metrics={'usage':result.get('usage'),'finish_reason':result['choices'][0].get('finish_reason')}
            if not isinstance(answer,str):
                raise ValueError('Provider did not return text')
            output=store.capture(answer or '[Empty model response]',kind='agent-interpretation',author=self.model,
                links=[{'relation':'derived_from','ref':r} for r in bundle['source_refs']])
            record={'run_id':event['id'],'status':'completed','started_at':started,'finished_at':now(),
                    'elapsed_seconds':round(time.monotonic()-start,3),'config':config,'metrics':metrics,
                    'output_ref':{'id':output['id'],'revision':output['revision']},'answer':answer,
                    'citation_check':{'expected':[r['id']+'@'+str(r['revision']) for r in bundle['source_refs']],
                        'missing':[r for r in bundle['source_refs'] if r['id']+'@'+str(r['revision']) not in answer]},
                    'limits':'Citation strings checked, not whether claims are supported. No tool calls are dispatched.'}
        except Exception as exc:
            # Provider error bodies can echo credentials or private prompts; never persist those bodies.
            record={'run_id':event['id'],'status':'failed','started_at':started,'finished_at':now(),
                    'elapsed_seconds':round(time.monotonic()-start,3),'config':config,
                    'error_type':type(exc).__name__,'http_status':getattr(exc,'code',None),
                    'message':'The model request failed. Source records remain saved. Check service reachability, configured model, context allowance and credential setup locally.'}
        store.event('run-finished',record)
        return record
