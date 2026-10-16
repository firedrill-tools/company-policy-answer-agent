"""Owned native Anthropic clients, raw evidence and completion boundary."""
from datetime import datetime,timezone
import hashlib
import json
from urllib.parse import urlsplit

from anthropic import AsyncAnthropic
import httpx2
from langchain_anthropic import ChatAnthropic
from pydantic import PrivateAttr

MAX_BODY=1_048_576
FIELDS=('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens')


def now():return datetime.now(timezone.utc).isoformat()
def sha(data):return hashlib.sha256(data).hexdigest()


def reported_usage(body):
    raw=body.get('usage') if isinstance(body,dict) else None
    fields={key:raw.get(key) if isinstance(raw,dict) and type(raw.get(key)) is int and 0<=raw[key]<=2**53-1 else None for key in FIELDS}
    complete=all(value is not None for value in fields.values())
    input_tokens=sum(fields[key] for key in (FIELDS[0],FIELDS[2],FIELDS[3])) if complete else None
    total=input_tokens+fields[FIELDS[1]] if complete else None
    complete=complete and total<=2**53-1
    return {'fields':fields,'complete':complete,'input_tokens':input_tokens if complete else None,
        'output_tokens':fields[FIELDS[1]] if complete else None,'total_tokens':total if complete else None,'cost_usd':None}


def aggregate_usage(observations):
    values=[o.get('reported_usage') for o in observations]
    fields={key:sum(u['fields'][key] for u in values) if values and all(u and u['fields'][key] is not None for u in values) else None for key in FIELDS}
    complete=bool(values) and all(u and u['complete'] for u in values)
    totals={key:sum(u[key] for u in values) if complete else None for key in ('input_tokens','output_tokens','total_tokens')}
    if any(value is not None and value>2**53-1 for value in (*fields.values(),*totals.values())):
        complete=False;totals=dict.fromkeys(totals)
        fields={key:value if value is None or value<=2**53-1 else None for key,value in fields.items()}
    return {'attempts':len(observations),'measured_attempts':sum(bool(u and u['complete']) for u in values),
        'complete':complete,'fields':fields,**totals,'cost_usd':None}


def endpoint(value):
    url=urlsplit(value)
    if not url.hostname or url.username or url.password or url.query or url.fragment or not (url.scheme=='https' or url.scheme=='http' and url.hostname in {'127.0.0.1','localhost','::1'}):
        raise ValueError('provider endpoint requires HTTPS or loopback HTTP without URL credentials/query/fragment')
    return value


class OwnedChatAnthropic(ChatAnthropic):
    """Pinned 1.7.6 ownership shim; native request/format/tool logic is inherited.

    That integration exposes no client constructor field; its two cached SDK
    properties otherwise create library-cached transports. Override only those
    accessors, never mutate a vendor cache or replace the model/agent loop.
    """
    _owned_async:AsyncAnthropic=PrivateAttr()

    def __init__(self,*,owned_async,**options):
        super().__init__(**options);self._owned_async=owned_async

    @property
    def _async_client(self):return self._owned_async

    @property
    def _client(self):raise RuntimeError('this run owns an async model; use ask_async or its synchronous ask wrapper')


class NativeEvidence:
    def __init__(self,callback,guard):self.observations=[];self.callback=callback;self.guard=guard;self.read_calls=0
    def publish(self):self.callback()

    async def request(self,request):
        self.guard()
        if len(self.observations)>=8:raise ValueError('policy model request limit (8) reached')
        raw=await request.aread();body=json.loads(raw)
        self.observations.append({'attempt':len(self.observations)+1,'status':'started','started_at':now(),'finished_at':None,
            'input_sha256':sha(raw),'requested_model':body.get('model'),'max_tokens':body.get('max_tokens'),'stream':body.get('stream',False),
            'http_status':None,'request_id':None,'body':None,'reported_usage':None,'response_model':None,'finish_reason':None,'error':None})
        self.publish()

    async def response(self,response):
        item=self.observations[-1];item.update(status='received',http_status=response.status_code,request_id=response.headers.get('request-id'))
        try:
            raw=await response.aread();item.update(body_sha256=sha(raw),truncated=len(raw)>MAX_BODY)
            text=raw[:MAX_BODY].decode('utf8',errors='replace')
            try:body=json.loads(text)
            except ValueError:body=text
            item.update(body=body,body_source='HTTP decoded response bytes before SDK validation',reported_usage=reported_usage(body))
            if isinstance(body,dict):item.update(response_id=body.get('id'),response_model=body.get('model'),finish_reason=body.get('stop_reason'))
            self.publish()
            if item['truncated']:raise ValueError('provider response exceeds 1 MiB evidence limit')
            if 200<=response.status_code<300:
                calls=validate_completion(body)
                reads=sum(call['name']!='SourceAnswer' for call in calls)
                if self.read_calls+reads>24:raise ValueError('policy read-tool limit (24) reached')
                self.read_calls+=reads;item['status']='accepted'
            else:item['status']='http_error'
            self.publish()
        except BaseException as error:
            item.update(status='rejected',error={'name':type(error).__name__,'message':str(error)})
            self.publish();raise
        finally:
            item['finished_at']=now();await response.aclose()

    def fail(self,error):
        if self.observations and self.observations[-1]['status'] in {'started','received'}:
            self.observations[-1].update(status='failed',finished_at=now(),error={'name':type(error).__name__,'message':str(error)})


def validate_completion(body):
    if not isinstance(body,dict) or body.get('type')!='message' or body.get('role')!='assistant' or not isinstance(body.get('id'),str) or not body['id'].strip():raise ValueError('provider did not return a completed message')
    content=body.get('content')
    if not isinstance(content,list) or not content or any(not isinstance(p,dict) for p in content):raise ValueError('provider content is empty or malformed')
    calls=[part for part in content if part.get('type')=='tool_use'];finish=body.get('stop_reason')
    if finish=='tool_use':
        if not calls or len(calls)>4:raise ValueError('expected 1–4 tool calls')
        if any(not isinstance(p.get('id'),str) or not p['id'].strip() or p.get('name') not in {'search_policies','get_policy','SourceAnswer'} or not isinstance(p.get('input'),dict) for p in calls):raise ValueError('invalid/unsupported tool call')
        if len({p['id'] for p in calls})!=len(calls):raise ValueError('duplicate tool call identity')
        if any(p['name']=='SourceAnswer' for p in calls) and len(calls)!=1:raise ValueError('answer cannot be mixed with source reads')
    elif finish=='end_turn' and not calls and any(p.get('type')=='text' and isinstance(p.get('text'),str) and p['text'].strip() for p in content):pass
    else:raise ValueError(f'provider response is unfinished or inconsistent ({finish!r})')
    return calls


def create_http(evidence,*,transport=None):
    return httpx2.AsyncClient(transport=transport,timeout=httpx2.Timeout(30,connect=5),follow_redirects=False,
        event_hooks={'request':[evidence.request],'response':[evidence.response]})
