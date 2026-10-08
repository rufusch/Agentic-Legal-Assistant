import json
import time
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.evidence import EvidenceBundle
from tests.test_common import upload, finish

class ResearchModel:
    metadata={'version':'research-test','kind':'local_llm','workflow':'research','trainable':True}
    def __init__(self):self.calls=0;self.omit=False
    def status(self):return {'ready':True}
    def complete(self,messages,schema,cancelled=lambda:False):
        self.calls+=1;p=json.loads(messages[-1]['content'])
        if 'items' in p:
            return {'decisions':[] if self.omit else [{'id':i['id'],'supported':True,'reason':'Source supports this proposition.'} for i in p['items']]}
        ref=next(s['source_id'] for s in p['sources'] if s['document_type']=='statute')
        return {'propositions':[{'section':'legal_framework','text':'The supplied test statute provides a hearing opportunity.','source_ids':[ref]},{'section':'executive_summary','text':'Invented proposition with an unknown source.','source_ids':['E999']}],'limitations':[]}

def wait(c,jid):
    until=time.monotonic()+15
    while time.monotonic()<until:
        job=c.get('/api/v1/jobs/'+jid).json()['data']
        if job['status'] in {'completed','completed_with_warnings','failed','cancelled'}:return job
        time.sleep(.03)
    raise AssertionError('Research timed out')

@pytest.fixture
def client(tmp_path):
    model=ResearchModel();app=create_app(tmp_path,{'a':'tenant-a','b':'tenant-b'},review_engine='extractive',research_llm=model)
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer a';yield c,model
    app.state.store.close()

def start(c,payload=None):
    r=c.post('/api/v1/research',json=payload or {'question':'Does the supplied statute require a hearing?'})
    assert r.status_code==202,r.text
    ticket=r.json()['data'];job=wait(c,ticket['job_id']);memo=c.get('/api/v1/research/'+ticket['research_id']).json()['data']
    return ticket,job,memo

def authority(c):
    ticket,_=upload(c,b'Test statute: the authority shall provide an opportunity of hearing.\n')
    rid=ticket['document_id'];finish(c,ticket)
    store=c.app.state.store
    with store.transaction():
        doc=store.get('tenant-a','document',rid);doc['metadata']={'document_type':'statute','jurisdiction':'IN','effective_from':'2020-01-01'};store.save('tenant-a','document',doc)
    return rid

def test_optional_context_abstains_and_validates(client):
    c,m=client;ticket,job,memo=start(c)
    assert job['status']=='completed_with_warnings' and not memo['claims'] and m.calls==0
    assert all(s['status']=='limited_evidence' for s in memo['sub_queries'])
    assert c.post('/api/v1/research',json={'question':'   '}).status_code==400
    assert c.post('/api/v1/research',json={'question':'Valid question','filters':{'date_from':'2026-01-01','date_to':'2020-01-01'}}).status_code==400
    assert c.get('/api/v1/home').json()['data']['workflows'][2]['available']
    for fmt,magic in [('json',b'{'),('pdf',b'%PDF'),('docx',b'PK')]:
        r=c.get(f'/api/v1/research/{memo["id"]}/export?format={fmt}');assert r.status_code==200 and r.content.startswith(magic)
    c.headers['Authorization']='Bearer b'
    assert c.get('/api/v1/research/'+memo['id']).status_code==404

def test_grounding_training_revocation_refinement_and_deletion(client):
    c,m=client;rid=authority(c)
    ticket,job,memo=start(c,{'question':'Does the statute provide a hearing?','context_document_ids':[rid],'filters':{'jurisdictions':['IN']}})
    assert job['status']=='completed_with_warnings',memo.get('failure')
    assert len(memo['claims'])==1 and 'Invented' not in json.dumps(memo)
    assert 'training_candidate' not in memo
    store=c.app.state.store
    EvidenceBundle(claims=memo['claims'],citations=memo['citations']).validate_source_spans(lambda d,ch:store.get('tenant-a','chunk',ch))
    path='/api/v1/models/research/dataset?format=sft'
    assert not c.get(path).text
    c.post(f'/api/v1/research/{memo["id"]}/feedback',json={'accepted':True,'use_for_training':True})
    row=json.loads(c.get(path).text);assert row['workflow']=='research' and row['source_hashes']
    assert 'Invented' not in row['messages'][-1]['content']
    c.post(f'/api/v1/research/{memo["id"]}/feedback',json={'accepted':True,'use_for_training':False})
    assert not c.get(path).text
    refined=c.post(f'/api/v1/research/{memo["id"]}/refine',json={'instruction':'Focus on the opportunity of hearing.'}).json()['data'];wait(c,refined['job_id'])
    assert c.get('/api/v1/research/'+refined['research_id']).json()['data']['parent_id']==memo['id']
    assert 'job.completed' in c.get('/api/v1/jobs/'+ticket['job_id']+'/events').text
    assert c.delete('/api/v1/documents/'+rid).status_code==200
    assert c.get('/api/v1/research/'+memo['id']).status_code==404
    assert not store.all('tenant-a','research_training')

def test_filters_and_incomplete_verification_fail_closed(client):
    c,m=client;rid=authority(c)
    _,_,memo=start(c,{'question':'What is the hearing requirement?','context_document_ids':[rid],'filters':{'jurisdictions':['IN-MH']}})
    assert not memo['claims'] and not m.calls
    m.omit=True
    _,job,memo=start(c)
    assert job['status']=='failed' and not memo['claims'] and not memo['citations']

def test_screenshot_anticipatory_bail_checklist(client):
    c,_=client
    r=c.post('/api/v1/drafts',json={'document_type':'Anticipatory Bail Application','jurisdiction':'IN-MH','court':'High Court of Bombay','instructions':'Prepare an anticipatory bail application.','supporting_document_ids':[]})
    assert r.status_code==202,r.text
    data=r.json()['data'];wait(c,data['job_id'])
    req=c.get('/api/v1/drafts/'+data['draft_id']+'/requirements').json()['data']
    keys={i['key'] for i in req['items']}
    assert {'applicant_name','arrest_status','allegations','case_number','court'}<=keys
