import asyncio
from datetime import date
import json
from pathlib import Path

import httpx2
import pytest

from policy_answer import evidence as evidence_module
from policy_answer.answer import PolicyAnswerService
from policy_answer.policies import PolicyCorpus
from test_native import CORPUS,DAY,Script,response,replies,run


@pytest.fixture(autouse=True)
def key(monkeypatch,isolated_output):
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic-not-real')
    monkeypatch.setenv('ANTHROPIC_MODEL','claude-sonnet-4-6')


def test_model_free_clarification_is_durable_and_uses_no_key(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY',raising=False)
    result=PolicyAnswerService(PolicyCorpus(CORPUS)).ask('What is the Wi-Fi password?',DAY)
    data=json.loads(Path(result['receipt_path']).read_text())
    assert result['answer']['status']=='insufficient' and result['execution_kind']=='model_free_clarification'
    assert data['status']=='completed' and data['provider_observations']==[] and data['reported_usage']['total_tokens'] is None


def test_changed_source_during_native_answer_rejects_stale_snapshot(tmp_path):
    file=tmp_path/'corpus.json';file.write_bytes(CORPUS.read_bytes());original=file.read_bytes()
    class Changing(Script):
        async def handle_async_request(self,request):
            value=await super().handle_async_request(request)
            if len(self.requests)==3:file.write_bytes(original+b'\n')
            return value
    script=Changing(replies())
    with pytest.raises(ValueError,match='corpus changed') as error:run(script,corpus=file)
    data=error.value.evidence
    assert data['status']=='failed' and data['result'] is None and data['final_source']['matches_loaded_snapshot'] is False
    assert data['initial_source']['sha256']==data['corpus_sha256'] and data['reported_usage']['total_tokens']==57
    assert script.closed and file.read_bytes()==original+b'\n'


def test_source_change_before_invocation_makes_no_model_request(tmp_path):
    file=tmp_path/'corpus.json';file.write_bytes(CORPUS.read_bytes());corpus=PolicyCorpus(file);file.write_bytes(file.read_bytes()+b'\n');script=Script([])
    with pytest.raises(ValueError,match='corpus changed') as error:
        PolicyAnswerService(corpus).ask('How many remote days?',DAY,transport=script)
    assert script.requests==[] and error.value.evidence['initial_source']['matches_loaded_snapshot'] is False


@pytest.mark.parametrize('where',['body','read','final'])
def test_recording_failure_stops_release_and_exposes_failed_publication(where,monkeypatch):
    original=evidence_module.publish;failed=[]
    def broken(path,data):
        hit=(where=='body' and data['provider_observations'] and data['provider_observations'][-1]['body'] is not None or
            where=='read' and bool(data['actions']) or where=='final' and data['status']=='completed')
        if hit and (where=='final' or not failed):failed.append(True);raise OSError('synthetic recording failure')
        return original(path,data)
    monkeypatch.setattr(evidence_module,'publish',broken);script=Script(replies())
    with pytest.raises(Exception) as error:run(script)
    data=error.value.evidence
    assert failed and script.closed and data['status']=='failed'
    if where=='body':assert len(script.requests)==1 and data['actions']==[]
    elif where=='read':assert len(script.requests)==1 and len(data['actions'])==1
    else:
        assert len(script.requests)==3 and 'recording failure' in data['evidence_error']
        assert json.loads(Path(error.value.receipt_path).read_text())['status']=='running'


def test_concurrent_readonly_invocations_own_independent_clients_and_evidence():
    async def exercise():
        service=PolicyAnswerService(PolicyCorpus(CORPUS));entered=asyncio.Event();closed=[]
        class Pending(httpx2.AsyncBaseTransport):
            async def handle_async_request(self,request):entered.set();await asyncio.Event().wait()
            async def aclose(self):closed.append(True)
        first=asyncio.create_task(service.ask_async('How many remote days?',DAY,transport=Pending()))
        await entered.wait();second_script=Script(replies())
        second=await service.ask_async('How many remote days?',DAY,transport=second_script)
        first.cancel()
        with pytest.raises(asyncio.CancelledError) as error:await first
        assert closed and second_script.closed and second['run_id']!=error.value.evidence['run_id']
        assert second['fetched']==['REMOTE-2026'] and error.value.evidence['fetched']==[]
        assert len(json.loads(Path(second['receipt_path']).read_text())['provider_observations'])==3
    asyncio.run(exercise())
