"""Immutable, byte-identified policy corpus and effective-date authority."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator


MAX_CORPUS_BYTES=4_194_304


def read_source(path):
    with Path(path).open('rb') as file:raw=file.read(MAX_CORPUS_BYTES+1)
    if len(raw)>MAX_CORPUS_BYTES:raise ValueError('policy corpus exceeds 4 MiB')
    return raw


class Policy(BaseModel):
    model_config=ConfigDict(frozen=True,extra='forbid')
    id:str=Field(min_length=1,max_length=100)
    topic:str=Field(min_length=1,max_length=100)
    title:str=Field(min_length=1,max_length=240)
    keywords:tuple[str,...]=Field(min_length=1,max_length=24)
    status:Literal['current','retired','draft']
    effective_from:date
    effective_until:date|None
    priority:int=Field(ge=0,le=100,strict=True)
    rule_code:str=Field(min_length=1,max_length=100)
    body:str=Field(min_length=1,max_length=16000)

    @field_validator('id','topic','title','rule_code','body')
    @classmethod
    def nonblank(cls,value):
        if not value.strip():raise ValueError('policy text cannot be blank')
        return value

    @field_validator('keywords')
    @classmethod
    def terms(cls,value):
        if any(not term.strip() or len(term)>100 for term in value) or len({term.casefold() for term in value})!=len(value):raise ValueError('invalid/duplicate keyword')
        return value

    @model_validator(mode='after')
    def interval(self):
        if self.effective_until is not None and self.effective_until<self.effective_from:raise ValueError('effective interval is reversed')
        if self.status=='retired' and self.effective_until is None:raise ValueError('retired policy requires its historical end date')
        return self

    def active(self,as_of:date):
        # Retired now can still be the legitimate authority for a historical date.
        return self.status!='draft' and self.effective_from<=as_of and (self.effective_until is None or as_of<=self.effective_until)


class PolicyCorpus:
    def __init__(self,path:str|Path):
        self.path=Path(path).resolve(strict=True);raw=read_source(self.path)
        self.sha256=hashlib.sha256(raw).hexdigest();data=json.loads(raw)
        if isinstance(data,dict):
            if data.get('synthetic') is not True or not isinstance(data.get('dataset'),dict):raise ValueError('wrapped corpus requires synthetic dataset identity')
            self.dataset=deep_identity(data['dataset']);rows=data.get('policies')
        else:self.dataset=None;rows=data
        if not isinstance(rows,list) or not rows or len(rows)>1000:raise ValueError('corpus must contain 1–1000 policy records')
        self.documents=tuple(Policy.model_validate(item) for item in rows)
        self.by_id=MappingProxyType({item.id:item for item in self.documents})
        if len(self.documents)!=len(self.by_id):raise ValueError('duplicate policy id')

    def topic_for(self,question:str):
        text=question.casefold();scores={}
        for doc in self.documents:
            score=sum(1 for term in doc.keywords if re.search(r'\b'+re.escape(term.casefold())+r'\b',text))
            scores[doc.topic]=max(scores.get(doc.topic,0),score)
        maximum=max(scores.values(),default=0)
        winners=[topic for topic,score in scores.items() if score==maximum and score>0]
        return winners[0] if len(winners)==1 else None

    def search(self,topic,as_of):
        docs=sorted((doc for doc in self.documents if doc.topic==topic),key=lambda doc:(not doc.active(as_of),-doc.priority,doc.id))
        return [{'id':doc.id,'title':doc.title,'status':doc.status,'active':doc.active(as_of),'priority':doc.priority,
            'effective_from':doc.effective_from.isoformat(),'effective_until':doc.effective_until.isoformat() if doc.effective_until else None,
            'summary':doc.body[:150]} for doc in docs]

    def fetch(self,policy_id):
        doc=self.by_id.get(policy_id)
        if doc is None:raise KeyError(f'unknown policy: {policy_id}')
        return doc.model_dump(mode='json')

    def active_authorities(self,topic,as_of):
        active=[doc for doc in self.documents if doc.topic==topic and doc.active(as_of)]
        highest=max((doc.priority for doc in active),default=None)
        return [doc for doc in active if doc.priority==highest]

    def has_conflict(self,topic,as_of):
        return len({doc.rule_code for doc in self.active_authorities(topic,as_of)})>1


def deep_identity(value):
    if not all(isinstance(value.get(key),str) and value[key].strip() for key in ('id','profile','case_id')) or type(value.get('version')) is not int or value['version']<1:raise ValueError('invalid dataset identity')
    return json.loads(json.dumps(value,allow_nan=False))
