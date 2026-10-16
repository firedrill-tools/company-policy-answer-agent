from datetime import date
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from policy_answer.answer import PolicyAnswerService
from policy_answer.datasets import data_root,initialize,list_cases,select
from policy_answer.policies import PolicyCorpus
from test_native import Script,response


def test_eleven_hash_bound_cases_and_private_copies_are_independent(tmp_path):
    manifest=list_cases();assert manifest['version']==1 and len(manifest['cases'])==11
    assert {c['profile'] for c in manifest['cases']}=={'starter','busy','ambiguous','boundary'}
    for case in manifest['cases']:
        file=tmp_path/f'{case["id"]}.json';copied=initialize(case['id'],file)
        assert file.stat().st_mode&0o777==0o600 and copied['sha256']==case['sha256']==hashlib.sha256(file.read_bytes()).hexdigest()
        assert copied['manifest_sha256']==manifest['manifest_sha256'] and PolicyCorpus(file).dataset['case_id']==case['id']
        before=file.read_bytes()
        with pytest.raises(FileExistsError):initialize(case['id'],file)
        assert file.read_bytes()==before


def test_native_busy_case_targets_authority_and_preserves_all_sources(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic-not-real')
    case,corpus,_=select('busy');before=corpus.path.read_bytes()
    assert len(corpus.documents)==24 and len({p.topic for p in corpus.documents})==8
    for topic in {p.topic for p in corpus.documents}:
        assert len(corpus.active_authorities(topic,date(2026,10,15)))==1
        assert not corpus.has_conflict(topic,date(2026,10,15))
        assert len(corpus.active_authorities(topic,date(2025,12,31)))==1
    output={'status':'answered','answer':'USD 110 exceeds USD 75, so obtain manager approval before ordering and submit the receipt within 30 days.','citations':['EXPENSE-2026']}
    script=Script([response('search_policies',{}),response('get_policy',{'policy_id':'EXPENSE-2026'}),response(args=output)])
    result=PolicyAnswerService(corpus).ask(case['question'],date.fromisoformat(case['as_of']),'claude-sonnet-4-6',transport=script)
    assert result['answer']==output and result['dataset']['case_id']=='busy' and script.closed
    assert corpus.path.read_bytes()==before and result['corpus_sha256']==hashlib.sha256(before).hexdigest()
    text=json.dumps(script.requests[-1]['messages'])
    assert 'EXPENSE-2026' in text and 'manager approval' in text and 'LEAVE-2026' not in text and 'manifest_sha256' not in text


def test_native_historical_case_cites_retired_version_only_within_its_interval(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic-not-real')
    case,corpus,_=select('historical-boundary');output={'status':'answered','answer':'The allowance on that date was up to three remote days per week.','citations':['REMOTE-2024']}
    script=Script([response('get_policy',{'policy_id':'REMOTE-2024'}),response(args=output)])
    result=PolicyAnswerService(corpus).ask(case['question'],date.fromisoformat(case['as_of']),'claude-sonnet-4-6',transport=script)
    assert result['answer']==output and '2025-12-31' in json.dumps(script.requests[0]['messages'])


@pytest.mark.parametrize('case_id',['ambiguous-topic','out-of-scope'])
def test_key_free_cases_do_not_create_provider_work(case_id,monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY',raising=False)
    case,corpus,_=select(case_id);result=PolicyAnswerService(corpus).ask(case['question'],date.fromisoformat(case['as_of']))
    assert result['execution_kind']=='model_free_clarification' and result['reported_usage']['attempts']==0


@pytest.mark.parametrize('mode',['hash','identity','path','duplicate','date'])
def test_dataset_drift_is_rejected_before_destination_creation(tmp_path,mode):
    root=tmp_path/'data';shutil.copytree(data_root(),root);file=root/'manifest.json';manifest=json.loads(file.read_text());case=manifest['cases'][0];target=root/case['file']
    if mode=='hash':target.write_bytes(target.read_bytes()+b'\n')
    elif mode=='identity':
        state=json.loads(target.read_text());state['dataset']['case_id']='wrong';raw=json.dumps(state).encode();target.write_bytes(raw);case['sha256']=hashlib.sha256(raw).hexdigest()
    elif mode=='path':case['file']='../escape.json'
    elif mode=='date':case['as_of']='2026-13-40'
    else:manifest['cases'][1]['id']=case['id']
    file.write_text(json.dumps(manifest));destination=tmp_path/'private.json'
    with pytest.raises(ValueError):initialize('starter',destination,root)
    assert not destination.exists()


def test_actual_cli_lists_initializes_runs_key_free_and_records_key_preflight(tmp_path):
    env={**os.environ};env.pop('ANTHROPIC_API_KEY',None)
    command=[sys.executable,'-m','policy_answer.cli']
    def run(*args):return subprocess.run([*command,*args],cwd=tmp_path,env=env,text=True,capture_output=True,timeout=12)
    listed=run('--list-cases');assert listed.returncode==0 and len(json.loads(listed.stdout)['cases'])==11
    file=tmp_path/'corpus.json';selected=run('--init-case','busy','--corpus',str(file));assert selected.returncode==0
    before=file.read_bytes();assert run('--init-case','starter','--corpus',str(file)).returncode==1 and file.read_bytes()==before
    free=run('--case','out-of-scope');assert free.returncode==0 and json.loads(free.stdout)['execution_kind']=='model_free_clarification'
    failure=run('--case','starter','--model','claude-sonnet-4-6');assert failure.returncode==1
    data=json.loads(Path(json.loads(failure.stderr)['receipt_path']).read_text())
    assert data['status']=='failed' and data['provider_observations']==[] and data['initial_source']['sha256']==data['final_source']['sha256']
