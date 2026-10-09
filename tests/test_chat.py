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
    assert job['status']=='failed' and job['failure']['code']=='MODEL_INVALID_VERIFICATION'
    assert not answer['content'] and not answer['claims'] and not answer['citations']
    assert not c.app.state.store.all('tenant-a','chat_training')


def test_document_reader_does_not_fetch_official_sources(client,monkeypatch):
    c,model=client;t,_=upload(c);finish(c,t)
    official=c.app.state.official_sources
    monkeypatch.setattr(official,'enabled',True)
    def unexpected(*args):raise AssertionError('Document reading must stay within the uploaded file')
    monkeypatch.setattr(official,'enrich',unexpected)
    cid=c.post('/api/v1/conversations',json={'title':'Read document','document_ids':[t['document_id']],'settings':{'include_official_sources':False}}).json()['data']['conversation_id']
    _,job,answer=send(c,cid,[t['document_id']])
    assert job['status']=='completed_with_warnings'
    assert answer['claims'] and answer['citations'][0]['document_id']==t['document_id']


def test_selected_agreement_precedes_supplemental_authorities(client, monkeypatch):
    c,model=client
    selected,_=upload(c);finish(c,selected)
    supplemental,_=upload(c,text=b'General statutory authority. Payment obligations under applicable legislation.',key='supplemental-upload')
    finish(c,supplemental)
    doc=c.app.state.store.get('tenant-a','document',supplemental['document_id'])
    official=c.app.state.official_sources
    monkeypatch.setattr(official,'enabled',True)
    monkeypatch.setattr(official,'enrich',lambda *args:{'enabled':True,'sources':[],'failures':[]})
    monkeypatch.setattr(official,'current_documents',lambda tenant:[doc])
    from backend import chat
    monkeypatch.setattr(chat,'source_budget',lambda *args:100)
    original=chat.search
    monkeypatch.setattr(chat,'search',lambda pool,q,n:sorted(original(pool,q,n),key=lambda chunk:chunk['document_id']==selected['document_id']))
    cid=conversation(c,[selected['document_id']])
    _,job,answer=send(c,cid,[selected['document_id']])
    assert job['status']=='completed_with_warnings'
    assert answer['claims']
    assert answer['citations'][0]['document_id']==selected['document_id']


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


def test_reader_paragraph_separates_upload_from_official_law(client):
    c,model=client;t,_=upload(c);finish(c,t);rid=t['document_id']
    cid=c.post('/api/v1/conversations',json={'document_ids':[rid],'settings':{'response_format':'document_summary','include_official_sources':False}}).json()['data']['conversation_id']
    _,job,answer=send(c,cid,[rid])
    assert job['status']=='completed_with_warnings'
    assert '\n' not in answer['content']
    assert not answer['content'].startswith('According to the selected source:')
    assert 'payment' in answer['content']
    assert answer['document_evidence']
    assert answer['legal_sources']==[] and answer['legal_context']==''
    assert 'certifies' not in answer['content']


def test_reader_only_lists_verified_government_authority(client, monkeypatch):
    from backend import official_sources
    c,model=client;t,_=upload(c);finish(c,t);rid=t['document_id']
    url='https://www.indiacode.nic.in/reader-test.pdf'
    monkeypatch.setattr(official_sources,'fetch',lambda u:(b'%PDF-official-test',url))
    c.app.state.worker.parser=lambda *args:{'result':{'pages':[{'number':1,'text':'The Payment Act requires payment on the agreed date.'}],'warnings':[]}}
    service=c.app.state.official_sources
    monkeypatch.setattr(service,"enabled",True)
    monkeypatch.setattr(service,'discover',lambda question,limit:[{'title':'Payment Act, 2026','url':url,'document_type':'statute'}])
    def complete(messages,schema,cancelled=lambda:False):
        packet=json.loads(messages[-1]['content'])
        if 'items' in packet:
            return {'decisions':[{'id':i['id'],'supported':True,'reason':'Source supports statement.'} for i in packet['items']]}
        doc=next(s['source_id'] for s in packet['sources'] if s['document_type']!='statute')
        law=next(s['source_id'] for s in packet['sources'] if s['document_type']=='statute')
        return {'propositions':[
            {'text':'The contract says payment is due on 15 October.','kind':'fact','source_ids':[doc]},
            {'text':'The Payment Act requires payment on the agreed date.','kind':'legal','source_ids':[law]},
            {'text':'Unattributed legal statement.','kind':'legal','source_ids':[law]}]}
    monkeypatch.setattr(model,'complete',complete)
    cid=c.post('/api/v1/conversations',json={'document_ids':[rid],'settings':{'response_format':'document_summary','include_official_sources':True}}).json()['data']['conversation_id']
    _,job,answer=send(c,cid,[rid])
    assert job['status']=='completed_with_warnings'
    assert answer['legal_sources'] and all(s['source_url']==url for s in answer['legal_sources'])
    assert 'Payment Act' in answer['legal_context'] and 'Unattributed' not in answer['legal_context']
    assert 'Payment Act' not in answer['content']
    assert all(s['document_id']==rid for s in answer['document_evidence'])
