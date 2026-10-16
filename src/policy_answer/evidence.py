"""Private application run evidence; no provider configuration is copied."""
from copy import deepcopy
from importlib.metadata import version
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from .runtime import aggregate_usage,now,sha
from .policies import read_source


def source_state(corpus):
    try:
        raw=read_source(corpus.path)
        return {'path':str(corpus.path),'sha256':sha(raw),'matches_loaded_snapshot':sha(raw)==corpus.sha256,'error':None}
    except Exception as error:return {'path':str(corpus.path),'sha256':None,'matches_loaded_snapshot':False,'error':str(error)}


def publish(path,data):
    staged=None
    try:
        with NamedTemporaryFile(mode='w',encoding='utf8',dir=path.parent,prefix='.receipt-',suffix='.tmp',delete=False) as file:
            staged=Path(file.name);json.dump(data,file,indent=2,allow_nan=False);file.write('\n');file.flush();os.fsync(file.fileno())
        os.replace(staged,path)
    finally:
        if staged is not None:staged.unlink(missing_ok=True)


class Receipt:
    def __init__(self,corpus,question,as_of,model,output_root=None):
        self.corpus=corpus;root=Path(output_root) if output_root is not None else Path.cwd()/'.runs'
        root.mkdir(parents=True,exist_ok=True,mode=0o700);run_id=str(uuid4());directory=root/run_id;directory.mkdir(mode=0o700)
        self.path=directory/'receipt.json';self.native=None;self.matched=set();self.recording_error=None
        self.data={'schema_version':1,'run_id':run_id,'receipt_path':str(self.path),'status':'running','started_at':now(),'finished_at':None,
            'question':question,'question_sha256':sha(question.encode()),'as_of':as_of.isoformat(),'requested_model':model,
            'versions':{name:version(name) for name in ('langchain','langgraph','langchain-anthropic','anthropic','httpx2')},
            'corpus_sha256':corpus.sha256,'dataset':corpus.dataset,'initial_source':source_state(corpus),'final_source':None,
            'provider_observations':[],'reported_usage':aggregate_usage([]),'actions':[],'fetched':[],'sdk_messages':[],
            'result':None,'error':None,'execution_kind':'not_started'}

    def guard(self):
        if self.recording_error is not None:raise self.recording_error

    def save(self):
        if self.native:self.data['provider_observations']=deepcopy(self.native.observations)
        self.data['reported_usage']=aggregate_usage(self.data['provider_observations'])
        try:publish(self.path,self.data)
        except BaseException as error:self.recording_error=error;raise

    def action(self,name,args,result):
        step=self.native.observations[-1] if self.native and self.native.observations else None
        tool_id=None
        if step and isinstance(step.get('body'),dict):
            for call in step['body'].get('content',[]):
                if isinstance(call,dict) and call.get('type')=='tool_use' and call.get('name')==name and call.get('input')==args and call.get('id') not in self.matched:
                    tool_id=call['id'];self.matched.add(tool_id);break
        self.data['actions'].append({'number':len(self.data['actions'])+1,'at':now(),'model_attempt':step['attempt'] if step else None,
            'tool_call_id':tool_id,'name':name,'args':deepcopy(args),'result':deepcopy(result)})
        self.save()

    def finish(self,result,error,fetched):
        self.data.update(status='failed' if error is not None else 'completed',finished_at=now(),result=result,
            fetched=sorted(fetched),final_source=source_state(self.corpus))
        if error is not None:
            causes=[];current=error
            while current is not None and len(causes)<5:
                causes.append({'name':type(current).__name__,'message':str(current),'http_status':getattr(current,'status_code',None)})
                current=current.__cause__
            self.data['error']={'name':type(error).__name__,'message':str(error),'causes':causes}
        self.save()
