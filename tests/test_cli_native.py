"""Ordinary CLI with actual SDK on an explicit local HTTP endpoint."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Event,Thread

import pytest

from test_native import response


@contextmanager
def provider(mode):
    requests=[];entered=Event();release=Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));entered.set()
            if mode=='cancel':release.wait(12);return
            status=503 if mode=='failure' and len(requests)>1 else 200
            body={'error':{'type':'api_error','message':'Synthetic provider unavailable'}} if status==503 else response('get_policy',{'policy_id':'REMOTE-2026'}) if len(requests)==1 else response()
            raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('request-id','loopback-synthetic');self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',requests,entered
    finally:release.set();server.shutdown();server.server_close();thread.join(timeout=3)


@pytest.mark.parametrize('mode',['success','failure','cancel'])
def test_normal_cli_native_output_failure_and_signal_are_durable(tmp_path,mode):
    with provider(mode) as (url,requests,entered):
        env={**os.environ,'ANTHROPIC_API_KEY':'synthetic-not-real','NO_PROXY':'127.0.0.1,localhost','no_proxy':'127.0.0.1,localhost'}
        process=subprocess.Popen([sys.executable,'-m','policy_answer.cli','--case','starter','--model','claude-sonnet-4-6','--base-url',url],cwd=tmp_path,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            assert entered.wait(8),'CLI did not reach local provider'
            if mode=='cancel':process.send_signal(signal.SIGTERM)
            stdout,stderr=process.communicate(timeout=10)
        finally:
            if process.poll() is None:process.kill();process.communicate()
    files=list((tmp_path/'.runs').glob('*/receipt.json'));assert len(files)==1;data=json.loads(files[0].read_text())
    assert data['initial_source']['sha256']==data['final_source']['sha256'] and 'synthetic-not-real' not in json.dumps(data)
    if mode=='success':
        assert process.returncode==0,stderr
        result=json.loads(stdout);assert result['answer']['status']=='answered' and result['fetched']==['REMOTE-2026']
        assert data['status']=='completed' and len(requests)==2 and data['reported_usage']['total_tokens']==38
    else:
        assert process.returncode==(130 if mode=='cancel' else 1),stderr
        failure=json.loads(stderr.splitlines()[-1]);assert failure['receipt_path']==str(files[0]) and data['status']=='failed' and data['result'] is None
        if mode=='cancel':assert len(requests)==1 and data['provider_observations'][0]['status']=='failed'
        else:assert len(requests)==2 and data['fetched']==['REMOTE-2026'] and data['provider_observations'][-1]['http_status']==503
        assert data['reported_usage']['total_tokens'] is None
