"""Actual LangChain graph/ChatAnthropic/Anthropic HTTP; no scripted agent."""
import asyncio
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import httpx2
import pytest

from policy_answer import answer as answer_module
from policy_answer.answer import PolicyAnswerService
from policy_answer.policies import PolicyCorpus

ROOT=Path(__file__).parents[1];CORPUS=ROOT/'fixtures/policies.json';DAY=date(2026,10,15)
USAGE={'input_tokens':10,'output_tokens':2,'cache_creation_input_tokens':3,'cache_read_input_tokens':4}
ANSWER={'status':'answered','answer':'Up to two remote days per workweek with manager scheduling approval.','citations':['REMOTE-2026']}


def response(name='SourceAnswer',args=ANSWER,finish='tool_use'):
    return {'id':'msg-synthetic','type':'message','role':'assistant','model':'claude-sonnet-4-6-synthetic',
        'content':[{'type':'tool_use','id':f'call-{name}','name':name,'input':deepcopy(args)}],
        'stop_reason':finish,'stop_sequence':None,'usage':deepcopy(USAGE),'unknown_marker':{'original':True}}


def replies(final=None):return [response('search_policies',{}),response('get_policy',{'policy_id':'REMOTE-2026'}),final or response()]


class Script(httpx2.AsyncBaseTransport):
    def __init__(self,items):self.items=iter(items);self.requests=[];self.closed=False
    async def handle_async_request(self,request):
        self.requests.append(json.loads(request.content));value=next(self.items)
        if isinstance(value,int):return httpx2.Response(value,json={'error':{'type':'api_error','message':'Synthetic provider unavailable'},'usage':deepcopy(USAGE)},headers={'request-id':'req-failed'})
        if isinstance(value,bytes):return httpx2.Response(200,content=value,headers={'content-type':'application/json','request-id':'req-malformed'})
        return httpx2.Response(200,json=value,headers={'request-id':'req-synthetic'})
    async def aclose(self):self.closed=True


@pytest.fixture(autouse=True)
def config(monkeypatch,isolated_output):
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic-not-a-provider-key')
    monkeypatch.setenv('ANTHROPIC_MODEL','claude-sonnet-4-6')


def run(script,corpus=CORPUS,**options):return PolicyAnswerService(PolicyCorpus(corpus)).ask('How many remote days?',DAY,transport=script,**options)


def test_native_graph_search_fetch_and_typed_answer_preserve_original_evidence():
    script=Script(replies());result=run(script);data=json.loads(Path(result['receipt_path']).read_text())
    assert result['answer']==ANSWER and result['fetched']==['REMOTE-2026'] and script.closed and len(script.requests)==3
    assert all(r['model']=='claude-sonnet-4-6' and r['max_tokens']==4096 and not r.get('stream',False) for r in script.requests)
    assert {t['name'] for t in script.requests[0]['tools']}=={'search_policies','get_policy','SourceAnswer'}
    assert 'manager scheduling approval' in json.dumps(script.requests[2]['messages'])
    assert data['status']=='completed' and data['execution_kind']=='native_langchain_anthropic'
    assert [a['name'] for a in data['actions']]==['search_policies','get_policy']
    assert data['actions'][1]['tool_call_id']=='call-get_policy' and data['actions'][1]['model_attempt']==2
    assert data['provider_observations'][-1]['body']==response() and data['provider_observations'][-1]['request_id']=='req-synthetic'
    assert data['reported_usage']['input_tokens']==51 and data['reported_usage']['total_tokens']==57 and data['reported_usage']['cost_usd'] is None
    assert len(data['sdk_messages'])==3 and 'synthetic-not-a-provider-key' not in json.dumps(data)
    assert data['initial_source']['sha256']==data['final_source']['sha256']==result['corpus_sha256']
    assert Path(result['receipt_path']).stat().st_mode&0o777==0o600 and Path(result['receipt_path']).parent.stat().st_mode&0o777==0o700


@pytest.mark.parametrize('finish',['max_tokens','end_turn','pause_turn','refusal',None])
def test_native_nonfinal_structured_answer_cannot_complete(finish):
    script=Script(replies(response(finish=finish)))
    with pytest.raises(Exception) as error:run(script)
    data=error.value.evidence
    assert len(script.requests)==3 and script.closed and data['status']=='failed' and data['result'] is None
    assert data['provider_observations'][-1]['finish_reason']==finish and data['provider_observations'][-1]['status']=='rejected'
    assert data['reported_usage']['total_tokens']==57 and data['fetched']==['REMOTE-2026']


def test_native_truncated_read_call_never_dispatches_a_source_tool():
    script=Script([response('get_policy',{'policy_id':'REMOTE-2026'},'max_tokens')])
    with pytest.raises(Exception) as error:run(script)
    assert script.closed and len(script.requests)==1 and error.value.evidence['actions']==[] and error.value.evidence['fetched']==[]


@pytest.mark.parametrize('mode',['missing','partial','zero','invalid'])
def test_raw_usage_is_not_inferred_from_sdk_defaults(mode):
    bodies=replies()
    for body in bodies:
        if mode=='missing':body.pop('usage')
        elif mode=='partial':body['usage']={'input_tokens':0,'output_tokens':0}
        elif mode=='zero':body['usage']=dict.fromkeys(USAGE,0)
        else:body['usage']={**USAGE,'input_tokens':True}
    script=Script(bodies)
    try:result=run(script);data=json.loads(Path(result['receipt_path']).read_text())
    except Exception as error:data=error.evidence
    assert data['reported_usage']['complete'] is (mode=='zero') and data['reported_usage']['total_tokens']==(0 if mode=='zero' else None)
    assert data['provider_observations'][0]['body']==bodies[0] and script.closed


def test_native_failure_after_fetch_retains_original_progress_and_failed_measurements():
    script=Script([response('get_policy',{'policy_id':'REMOTE-2026'}),503])
    with pytest.raises(Exception) as error:run(script)
    data=error.value.evidence
    assert len(script.requests)==2 and script.closed and data['fetched']==['REMOTE-2026']
    assert data['provider_observations'][-1]['http_status']==503 and data['provider_observations'][-1]['request_id']=='req-failed'
    assert data['reported_usage']['total_tokens']==38 and data['result'] is None


@pytest.mark.parametrize('mode',['invalid-json','oversized','unknown-tool','mixed-output','duplicate-call','blank-output'])
def test_native_malformed_or_unsupported_output_retains_failure_without_answer(mode):
    body=response()
    if mode=='invalid-json':body=b'{synthetic-invalid-json'
    elif mode=='oversized':body=(json.dumps(body)+' '*1_048_576).encode()
    elif mode=='unknown-tool':body['content'][0]['name']='change_policy'
    elif mode=='mixed-output':body['content'].append(response('get_policy',{'policy_id':'REMOTE-2026'})['content'][0])
    elif mode=='duplicate-call':body=response('get_policy',{'policy_id':'REMOTE-2026'});body['content'].append(deepcopy(body['content'][0]))
    else:body.update(content=[{'type':'text','text':'  '}],stop_reason='end_turn')
    script=Script([body])
    with pytest.raises(Exception) as error:run(script)
    assert len(script.requests)==1 and script.closed and error.value.evidence['actions']==[]
    assert error.value.evidence['provider_observations'][0]['body'] is not None


def test_native_validation_error_has_no_framework_repair_request():
    script=Script([response('get_policy',{'policy_id':'REMOTE-2026'}),response(args={**ANSWER,'status':'invented'})])
    with pytest.raises(Exception) as error:run(script)
    assert len(script.requests)==2 and script.closed and error.value.evidence['status']=='failed'


def test_native_loop_budget_preserves_reads_without_an_answer():
    script=Script([response('get_policy',{'policy_id':'REMOTE-2026'})]*10)
    with pytest.raises(Exception) as error:run(script)
    assert 1<=len(script.requests)<=8 and script.closed and error.value.evidence['result'] is None
    assert error.value.evidence['actions'] and error.value.evidence['fetched']==['REMOTE-2026']


@pytest.mark.parametrize('mode',['cancel','deadline'])
def test_native_cancellation_and_deadline_close_owned_transport(mode):
    async def exercise():
        entered=asyncio.Event();cancelled=[];closed=[]
        class Pending(httpx2.AsyncBaseTransport):
            async def handle_async_request(self,request):
                entered.set()
                try:await asyncio.Event().wait()
                finally:cancelled.append(True)
            async def aclose(self):closed.append(True)
        task=asyncio.create_task(PolicyAnswerService(PolicyCorpus(CORPUS)).ask_async('How many remote days?',DAY,transport=Pending(),timeout_seconds=0.04 if mode=='deadline' else 120))
        await entered.wait()
        if mode=='cancel':task.cancel()
        with pytest.raises(TimeoutError if mode=='deadline' else asyncio.CancelledError) as error:await task
        assert closed and cancelled and error.value.evidence['status']=='failed'
        assert error.value.evidence['provider_observations'][0]['status']=='failed' and error.value.evidence['reported_usage']['total_tokens'] is None
    asyncio.run(exercise())


def test_owned_clients_close_when_native_chat_construction_fails(monkeypatch):
    script=Script([])
    def broken(**_):raise RuntimeError('synthetic chat startup failure')
    monkeypatch.setattr(answer_module,'OwnedChatAnthropic',broken)
    with pytest.raises(RuntimeError,match='startup failure'):run(script)
    assert script.closed and script.requests==[]


def test_native_parallel_source_reads_keep_distinct_tool_feedback_and_citations():
    body=response('get_policy',{'policy_id':'REMOTE-2026'})
    archived=response('get_policy',{'policy_id':'REMOTE-2024'})['content'][0];archived['id']='call-archived';body['content'].append(archived)
    script=Script([body,response()]);result=run(script)
    data=json.loads(Path(result['receipt_path']).read_text())
    assert result['answer']==ANSWER and result['fetched']==['REMOTE-2024','REMOTE-2026'] and script.closed
    assert {a['tool_call_id'] for a in data['actions']}=={'call-get_policy','call-archived'}
    prompt=json.dumps(script.requests[-1]['messages'])
    assert 'Historical allowance' in prompt and 'two days per workweek' in prompt and len(script.requests)==2
