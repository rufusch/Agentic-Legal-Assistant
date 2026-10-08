import json
import time
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.evidence import EvidenceBundle
from tests.test_common import upload, finish
from tests.test_research import wait


class ChatModel:
    metadata={'version':'chat-test','kind':'local_llm','trainable':True}
    def __init__(self): self.calls=0;self.omit=False
    def status(self): return {'ready':True}
    def complete(self,messages,schema,cancelled=lambda:False):
        self.calls+=1;p=json.loads(messages[-1]['content'])
        if 'items' in p:
            return {'decisions':[] if self.omit else [{'id':i['id'],'supported':True,'reason':'Supported by source.'} for i in p['items']]}
        ref=p['sources'][0]['source_id']
        return {'propositions':[
            {'text':'The supplied contract says payment is due on 15 October.','kind':'fact','source_ids':[ref]},
            {'text':'Invented unknown-source claim.','kind':'fact','source_ids':['E999']},
            {'text':'The law certifies enforceability.','kind':'legal','source_ids':[ref]}]}


@pytest.fixture
def client(tmp_path):
    model=ChatModel();app=create_app(tmp_path,{'a':'tenant-a','b':'tenant-b'},review_engine='extractive',chat_llm=model)
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer a';yield c,model
    app.state.store.close()


def conversation(c,ids=None):
    r=c.post('/api/v1/conversations',json={'title':'Integration chat','document_ids':ids or []})
    assert r.status_code==201,r.text
    return r.json()['data']['conversation_id']


def send(c,cid,ids=None,key='message-1'):
    r=c.post(f'/api/v1/conversations/{cid}/messages',json={'content':'When is payment due?','selected_document_ids':ids or []},headers={'Idempotency-Key':key})
    assert r.status_code==202,r.text
    ticket=r.json()['data'];job=wait(c,ticket['job_id'])
    answer=next(m for m in c.get(f'/api/v1/conversations/{cid}/messages').json()['data'] if m['id']==ticket['assistant_message_id'])
    return ticket,job,answer


def test_chat_without_evidence_abstains_and_is_tenant_scoped(client):
    c,model=client;cid=conversation(c);ticket,job,answer=send(c,cid)
    assert job['status']=='completed_with_warnings' and model.calls==0
    assert not answer['claims'] and 'not provide enough' in answer['content']
    assert c.post(f'/api/v1/conversations/{cid}/messages',json={'content':'   '}).status_code==400
    assert c.get('/api/v1/home').json()['data']['workflows'][3]['available']
    models=c.get('/api/v1/models').json()['data']
    assert next(m for m in models if m['workflow']=='chat')['version']=='chat-test'
    c.headers['Authorization']='Bearer b'
    assert c.get(f'/api/v1/conversations/{cid}/messages').status_code==404
    assert c.post(f'/api/v1/conversations/{cid}/messages',json={'content':'Hello'}).status_code==404
    assert not c.get('/api/v1/conversations').json()['data']['items']


def test_chat_grounding_feedback_revocation_idempotency_and_deletion(client):
    c,model=client;t,_=upload(c);finish(c,t);rid=t['document_id'];cid=conversation(c,[rid])
    ticket,job,answer=send(c,cid,[rid]);assert job['status']=='completed_with_warnings'
    assert len(answer['claims'])==1 and 'Invented' not in answer['content'] and 'certifies' not in answer['content']
    bundle=EvidenceBundle.model_validate(answer)
    bundle.validate_source_spans(lambda d,ch:c.get(f'/api/v1/documents/{d}/chunks/{ch}').json()['data'])
    assert model.calls==2
    repeated=c.post(f'/api/v1/conversations/{cid}/messages',json={'content':'When is payment due?','selected_document_ids':[rid]},headers={'Idempotency-Key':'message-1'})
    assert repeated.json()['data']==ticket and model.calls==2
    mid=answer['id'];path=f'/api/v1/conversations/{cid}/messages/{mid}/feedback'
    dataset='/api/v1/models/chat/training-dataset'
    assert c.get(dataset).text==''
    assert c.post(path,json={'accepted':True,'use_for_training':True}).json()['data']['training_eligible']
    row=json.loads(c.get(dataset).text)
    assert c.get('/api/v1/models/chat/dataset?format=sft').text==c.get(dataset).text
    target=json.loads(row['messages'][-1]['content']);assert len(target['propositions'])==1
    assert 'Invented' not in json.dumps(target)
    c.post(path,json={'accepted':False,'use_for_training':False});assert c.get(dataset).text==''
    c.post(path,json={'accepted':True,'use_for_training':True})
    assert c.delete('/api/v1/documents/'+rid).status_code==200
    assert c.get(dataset).text=='' and c.get(f'/api/v1/conversations/{cid}/messages').status_code==404
    assert c.get('/api/v1/jobs/'+ticket['job_id']).status_code==404


def test_chat_incomplete_verification_fails_closed(client):
    c,model=client;model.omit=True;t,_=upload(c);finish(c,t);cid=conversation(c,[t['document_id']])
    _,job,answer=send(c,cid,[t['document_id']])
    assert job['status']=='failed' and job['failure']['code']=='CHAT_VERIFICATION_FAILED'
    assert not answer['content'] and not answer['claims'] and not answer['citations']
    assert not c.app.state.store.all('tenant-a','chat_training')


def test_chat_busy_cancellation_and_restart(tmp_path):
    model=ChatModel();app=create_app(tmp_path,{'a':'tenant-a'},start_worker=False,review_engine='extractive',chat_llm=model)
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer a';cid=conversation(c)
        path=f'/api/v1/conversations/{cid}/messages'
        ticket=c.post(path,json={'content':'First question'}).json()['data']
        assert c.post(path,json={'content':'Second question'}).status_code==409
        assert c.post('/api/v1/jobs/'+ticket['job_id']+'/cancel').json()['data']['status']=='cancelled'
        assert next(m for m in c.get(path).json()['data'] if m['role']=='assistant')['status']=='cancelled'
        pending=c.post(path,json={'content':'Third question'}).json()['data']
    app.state.store.close()
    app=create_app(tmp_path,{'a':'tenant-a'},review_engine='extractive',chat_llm=model)
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer a';assert wait(c,pending['job_id'])['status']=='completed_with_warnings'
        assert len(c.get(path).json()['data'])==4
    app.state.store.close()
