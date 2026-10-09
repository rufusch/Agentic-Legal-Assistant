import copy
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.drafting_engine import validate_final
from backend.drafting_engine import supported_block
from backend.drafting_engine import recover_source_refs
from backend.models.review_llm import LocalReviewLLM, ReviewModelError
from tests.test_common import upload, finish


def test_court_holding_cannot_use_only_intake_even_when_mislabelled_fact():
    from types import SimpleNamespace
    item={'text':'The Supreme Court held that bail must be granted.','statement_type':'fact','source_ids':['E1']}
    catalog={'E1':{'quote':item['text'],'chunk':{'document_id':'intake'}}}
    docs={'intake':{'metadata':{'document_type':'user_input'}}}
    assert not supported_block(item,SimpleNamespace(supported=True,statement_type='fact'),catalog,docs)


def test_contractual_right_is_a_document_fact():
    from types import SimpleNamespace
    item={'text':'Either party has a right to terminate with 30 days notice.','statement_type':'fact','source_ids':['E1']}
    catalog={'E1':{'quote':item['text'],'chunk':{'document_id':'contract'}}}
    docs={'contract':{'metadata':{'document_type':'contract'}}}
    assert supported_block(item,SimpleNamespace(supported=True,statement_type='fact'),catalog,docs)


def test_missing_fact_citation_is_retrieved_without_promoting_intake_to_law():
    items=[{'text':'The applicant has no prior criminal antecedents.','statement_type':'fact','source_ids':[]},
           {'text':'The Supreme Court held that bail must be granted.','statement_type':'legal','source_ids':[]}]
    packet=[{'source_id':'E1','document_type':'user_input','text':'facts.grounds: The applicant has no prior criminal antecedents. The Supreme Court held that bail must be granted.'}]
    recover_source_refs(items,packet)
    assert items[0]['source_ids']==['E1']
    assert items[1]['source_ids']==[]


def test_structured_bail_intake_produces_a_cited_draft_without_model_invention(drafting_client):
    c,model=drafting_client
    facts={'applicant_name':'Example Applicant','case_number':'12/2026','allegations':'The complainant alleges a payment of INR 5000. The applicant disputes the allegation.',
           'arrest_status':'Arrested on 1 October 2026. The applicant is in judicial custody.',
           'grounds':'The applicant has a fixed residence.\nThe applicant has no prior criminal antecedents.\nThe Supreme Court held that bail is automatic under invented law.',
           'relief':'Regular bail on suitable conditions, including attendance before the trial court.'}
    response=c.post('/api/v1/drafts',json={'document_type':'Bail Application','jurisdiction':'IN','court':'Example Sessions Court','instructions':'Prepare a bail application using the supplied allegations.','facts':facts})
    data=response.json()['data'];wait(c,data['job_id'])
    draft,_=generate(c,data['draft_id'])
    assert draft['status']=='completed_with_warnings' and not model.calls
    sections={s['heading']:s for s in draft['sections']}
    assert {'Cause title','Background','Facts','Grounds','Authorities','Prayer','Proposed bail conditions','Signature'}<=sections.keys()
    text='\n'.join(b['text'] for s in draft['sections'] for b in s['blocks'])
    assert 'Example Applicant' in text and '5000' in text and 'fixed residence' in text
    assert 'bail is automatic' not in text and 'invented law' not in text
    assert draft['verification']['method']=='exact_captured_intake_fields'
    assert len(draft['unresolved_placeholders'])==3
    assert all(claim['citation_ids'] for claim in draft['claims'])
    validate_final(draft,c.app.state.store.all('tenant-a','chunk'))
    assert c.get('/api/v1/drafts/'+draft['id']+'/export?format=pdf').content.startswith(b'%PDF')


def test_notice_free_text_prefills_exact_values_and_produces_a_draft(drafting_client):
    c,model=drafting_client
    response=c.post('/api/v1/drafts',json={'document_type':'notice','jurisdiction':'IN','instructions':'Prepare a payment notice from Alpha Ltd to Beta Ltd, requesting payment of INR 5000 by 15 October 2026 for invoice INV-101 dated 1 October 2026.'})
    data=response.json()['data'];wait(c,data['job_id']);draft,_=generate(c,data['draft_id'])
    assert draft['status']=='completed_with_warnings' and not model.calls
    text='\n'.join(b['text'] for s in draft['sections'] for b in s['blocks'])
    for value in ('Alpha Ltd','Beta Ltd','INR 5000','15 October 2026','INV-101','1 October 2026'):assert value in text
    assert draft['facts']['demand']=='payment of INR 5000'
    validate_final(draft,c.app.state.store.all('tenant-a','chunk'))


def test_rejected_draft_block_is_repaired_and_checked_again(tmp_path):
    calls=[]
    class RepairModel(LocalReviewLLM):
        def status(self):return {'ready':True,'model':self.metadata}
        def complete(self,messages,schema,cancelled=lambda:False):
            payload=json.loads(messages[-1]['content']);calls.append(payload)
            if 'rejected_blocks' in payload:
                return {'repairs':[{'id':i['id'],'block':{'kind':'paragraph','text':'Please respond to this notice.','statement_type':'draft_language','source_ids':[]}} for i in payload['rejected_blocks']]}
            if 'blocks' in payload:
                return {'decisions':[{'id':i['id'],'supported':'fabricated' not in i['text'],'statement_type':i['declared_type'],'reason':'Unsupported law' if 'fabricated' in i['text'] else 'Proposed request'} for i in payload['blocks']]}
            return {'sections':[{'heading':'Notice','blocks':[{'kind':'paragraph','text':'The recipient must pay under fabricated statute 999.','statement_type':'legal','source_ids':[]}]}]}
    app=create_app(tmp_path,{'alice':'tenant-a'},review_engine='extractive',drafting_llm=RepairModel())
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer alice'
        rid=create(c);draft,_=generate(c,rid)
        assert draft['status']=='completed_with_warnings'
        assert draft['sections'][0]['blocks'][0]['text']=='Please respond to this notice.'
        assert draft['sections'][0]['blocks'][0]['verification_status']=='checked'
        assert sum('blocks' in p for p in calls)==2
    app.state.store.close()


class DraftModel:
    metadata={'id':'leximind-drafting','workflow':'drafting','version':'test-draft-v1','kind':'local_llm','trainable':True}
    def __init__(self):self.calls=[];self.mode='normal';self.cancelled=False
    def status(self):return {'ready':True,'message':'Test model ready','model':self.metadata}
    def complete(self,messages,schema,cancelled=lambda:False):
        self.calls.append(messages)
        if self.mode=='unavailable':raise ReviewModelError('MODEL_UNAVAILABLE','Test service unavailable')
        payload=json.loads(messages[-1]['content'])
        if 'blocks' in payload:
            result=[{'id':b['id'],'supported':'fabricated' not in b['text'],'statement_type':'fact' if 'hidden assertion' in b['text'] else b['declared_type'],'reason':'Checked against supplied evidence.'} for b in payload['blocks']]
            if self.mode=='omit_decision':result=result[:-1]
            return {'decisions':result}
        if 'edited_sections' in payload:
            return {'sections':[{'heading':s['heading'],'blocks':[{'kind':b['kind'],'text':b['text'],'statement_type':'draft_language','source_ids':[]} for b in s['blocks']]} for s in payload['edited_sections']]}
        if self.mode=='title_only':return {'sections':[{'heading':'Notice','blocks':[{'kind':'heading','text':'Payment reminder notice','statement_type':'draft_language','source_ids':[]}]}]}
        ref=next(s for s in payload['sources'] if 'facts.sender' in s['text'])
        return {'sections':[{'heading':'Facts','blocks':[
            {'kind':'paragraph','text':'The sender states that their name is Example Sender.','statement_type':'fact','source_ids':[ref['source_id']]},
            {'kind':'paragraph','text':'The recipient must pay under fabricated statute 999.','statement_type':'legal','source_ids':[ref['source_id']]},
            {'kind':'paragraph','text':'Please respond to this notice.','statement_type':'draft_language','source_ids':[]},
            {'kind':'paragraph','text':'An unknown witness confirmed everything.','statement_type':'fact','source_ids':['E999']},
            {'kind':'paragraph','text':'hidden assertion: the recipient was convicted.','statement_type':'draft_language','source_ids':[]},
        ]}]}


@pytest.fixture
def drafting_client(tmp_path):
    model=DraftModel()
    app=create_app(tmp_path,{'alice':'tenant-a','bob':'tenant-b'},review_engine='extractive',drafting_llm=model)
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer alice'
        yield client,model
    app.state.store.close()


def wait(client,job):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        data=client.get('/api/v1/jobs/'+job).json()['data']
        if data['status'] in {'completed','completed_with_warnings','failed','cancelled'}:return data
        time.sleep(.03)
    raise AssertionError('Draft job timed out')


def create(client,document_ids=None):
    response=client.post('/api/v1/drafts',json={'document_type':'notice','jurisdiction':'IN-MH','instructions':'Prepare a notice requesting a response.','facts':{'sender':'Example Sender'},'supporting_document_ids':document_ids or []},headers={'Idempotency-Key':'create-draft'})
    assert response.status_code==202,response.text
    data=response.json()['data'];assert wait(client,data['job_id'])['status']=='completed_with_warnings'
    return data['draft_id']


def generate(client,rid):
    gaps=client.get(f'/api/v1/drafts/{rid}/requirements').json()['data']['missing_requirement_ids']
    response=client.post(f'/api/v1/drafts/{rid}/generate',json={'proceed_with_missing_information':True,'acknowledged_requirement_ids':gaps},headers={'Idempotency-Key':'generate-'+rid})
    assert response.status_code==202,response.text
    job=response.json()['data'];wait(client,job['job_id'])
    return client.get('/api/v1/drafts/'+rid).json()['data'],job


def test_intake_acknowledgement_grounding_and_exports(drafting_client):
    client,model=drafting_client;rid=create(client)
    req=client.get(f'/api/v1/drafts/{rid}/requirements').json()['data']
    assert req['status']=='awaiting_information'
    assert not model.calls # The transparent checklist does not require a loaded model.
    assert client.post(f'/api/v1/drafts/{rid}/generate',json={}).status_code==409
    unknown=client.patch(f'/api/v1/drafts/{rid}/requirements',json={'answers':[{'requirement_id':'00000000-0000-0000-0000-000000000001','value':'x'}]})
    assert unknown.status_code==400
    report,job=generate(client,rid)
    assert report['status']=='completed_with_warnings',report.get('failure')
    assert len(report['claims'])==1
    assert report['claims'][0]['text']=='The sender states that their name is Example Sender.'
    assert any('[RECIPIENT]'==p['token'] for p in report['unresolved_placeholders'])
    texts=[b['text'] for s in report['sections'] for b in s['blocks']]
    assert not any('fabricated statute' in text or 'hidden assertion' in text for text in texts)
    assert report['retrieval']['selected_authority_chunks']==0
    sources=client.app.state.store.all('tenant-a','chunk')
    validate_final(report,sources)
    tampered=copy.deepcopy(report);tampered['claims'][0]['text']='Tampered fact'
    with pytest.raises(ValueError):validate_final(tampered,sources)
    for format,magic in [('txt',b'WORKING DRAFT'),('docx',b'PK'),('pdf',b'%PDF')]:
        response=client.get(f'/api/v1/drafts/{rid}/export?format={format}')
        assert response.status_code==200 and response.content.startswith(magic)
    events=client.get(f'/api/v1/jobs/{job["job_id"]}/events').text
    assert 'job.completed' in events and 'verifying' in events
    assert client.get('/api/v1/models').json()['data'][1]['workflow']=='drafting'


def test_title_only_output_is_not_a_completed_draft(drafting_client):
    c,model=drafting_client;rid=create(c);model.mode='title_only'
    draft,_=generate(c,rid)
    assert draft['status']=='failed' and draft['failure']['code']=='NO_SUPPORTED_DRAFT'


def test_blocking_fields_and_answers(drafting_client):
    client,_=drafting_client;rid=create(client)
    items=client.get(f'/api/v1/drafts/{rid}/requirements').json()['data']['items']
    jurisdiction=next(r for r in items if r['key']=='jurisdiction')
    response=client.patch(f'/api/v1/drafts/{rid}/requirements',json={'answers':[{'requirement_id':jurisdiction['id'],'value':''}]})
    assert response.status_code==200
    response=client.post(f'/api/v1/drafts/{rid}/generate',json={'proceed_with_missing_information':True})
    assert response.status_code==409 and response.json()['error']['code']=='BLOCKING_INFORMATION_REQUIRED'
    answers=[{'requirement_id':r['id'],'value':'IN-MH' if r['key']=='jurisdiction' else 'User supplied value'} for r in items]
    response=client.patch(f'/api/v1/drafts/{rid}/requirements',json={'answers':answers})
    assert response.json()['data']['status']=='ready_to_draft'


def test_edits_versions_training_consent_and_deletion(drafting_client):
    client,_=drafting_client;rid=create(client);draft,_=generate(client,rid)
    endpoint=f'/api/v1/drafts/{rid}/feedback'
    data='/api/v1/models/drafting/dataset?format=sft'
    assert client.get(data).text==''
    body={'accepted':True,'use_for_training':True,'base_version':draft['version']}
    assert client.post(endpoint,json=body).json()['data']['training_eligible']
    rows=[json.loads(line) for line in client.get(data).text.splitlines()]
    assert len(rows)==1 and rows[0]['workflow']=='drafting'
    assert 'fabricated statute' not in rows[0]['messages'][-1]['content']
    client.post(endpoint,json={**body,'use_for_training':False});assert client.get(data).text==''
    client.post(endpoint,json=body)
    section=draft['sections'][0]
    edit=client.patch(f'/api/v1/drafts/{rid}/sections/{section["id"]}',json={'text':'Please provide a response.','base_version':draft['version']})
    assert edit.status_code==200
    edited=edit.json()['data'];assert edited['needs_verification']
    assert edited['sections'][0]['blocks'][0]['claim_ids']==[]
    assert client.get(data).text==''
    assert client.get(f'/api/v1/drafts/{rid}/export?format=txt').status_code==409
    assert client.patch(f'/api/v1/drafts/{rid}/sections/{section["id"]}',json={'text':'stale edit','base_version':draft['version']}).status_code==409
    response=client.post(f'/api/v1/drafts/{rid}/verify',json={})
    assert wait(client,response.json()['data']['job_id'])['status']=='completed_with_warnings'
    verified=client.get('/api/v1/drafts/'+rid).json()['data']
    assert not verified['needs_verification']
    assert verified['sections'][0]['blocks'][0]['text']=='Please provide a response.'
    assert client.get(f'/api/v1/drafts/{rid}/versions').json()['data']['items']
    source=verified['context_document_id']
    assert client.delete('/api/v1/documents/'+source).status_code==200
    assert client.get('/api/v1/drafts/'+rid).status_code==404
    assert not client.app.state.store.all('tenant-a','draft_training')


def test_tenant_boundaries_and_failed_model(drafting_client):
    client,model=drafting_client;rid=create(client)
    client.headers['Authorization']='Bearer bob'
    for path in [f'drafts/{rid}',f'drafts/{rid}/requirements',f'drafts/{rid}/versions']:
        assert client.get('/api/v1/'+path).status_code==404
    client.headers['Authorization']='Bearer alice';model.mode='unavailable'
    draft,job=generate(client,rid)
    assert draft['status']=='failed' and draft['failure']['code']=='MODEL_UNAVAILABLE'
    assert not draft['sections']
    assert client.get(f'/api/v1/drafts/{rid}/export?format=txt').status_code==409


def test_verification_must_cover_every_block(drafting_client):
    client,model=drafting_client;rid=create(client);model.mode='omit_decision'
    draft,_=generate(client,rid)
    assert draft['failure']['code']=='MODEL_INVALID_VERIFICATION'
    assert not draft['sections']


def test_retrieval_authority_scope_and_source_deletion(drafting_client):
    client,model=drafting_client
    ticket,_=upload(client,b'Notice response: a synthetic statute excerpt for test only.','authority-upload')
    finish(client,ticket)
    store=client.app.state.store
    doc=store.get('tenant-a','document',ticket['document_id']);doc['metadata'].update(document_type='statute',jurisdiction='US');store.save('tenant-a','document',doc)
    rid=create(client,[doc['id']]);draft,_=generate(client,rid)
    assert draft['retrieval']['selected_authority_chunks']==0
    assert all(s['document_type']!='statute' for s in json.loads(model.calls[0][-1]['content'])['sources'])
    assert client.delete('/api/v1/documents/'+doc['id']).status_code==200
    assert client.get('/api/v1/drafts/'+rid).status_code==404


def test_cancellation_and_idempotent_generation(drafting_client):
    import threading
    from backend.models.review_llm import ReviewCancelled
    client,model=drafting_client;rid=create(client)
    original=model.complete;started=threading.Event()
    def slow(messages,schema,cancelled=lambda:False):
        started.set()
        while not cancelled():time.sleep(.02)
        raise ReviewCancelled()
    model.complete=slow
    gaps=client.get(f'/api/v1/drafts/{rid}/requirements').json()['data']['missing_requirement_ids']
    body={'proceed_with_missing_information':True,'acknowledged_requirement_ids':gaps}
    headers={'Idempotency-Key':'retry-the-same-generation'}
    first=client.post(f'/api/v1/drafts/{rid}/generate',json=body,headers=headers)
    assert first.status_code==202
    replay=client.post(f'/api/v1/drafts/{rid}/generate',json=body,headers=headers)
    assert replay.json()==first.json()
    assert started.wait(3)
    jid=first.json()['data']['job_id']
    assert client.post('/api/v1/jobs/'+jid+'/cancel',json={}).json()['data']['status']=='cancelled'
    assert client.get('/api/v1/drafts/'+rid).json()['data']['status']=='cancelled'
    assert client.get(f'/api/v1/drafts/{rid}/export?format=txt').status_code==409
    assert client.app.state.store.db.execute('SELECT COUNT(*) FROM queue WHERE job=?',(jid,)).fetchone()[0]==0
    model.complete=original


def test_independent_drafting_model_activation(tmp_path,monkeypatch):
    monkeypatch.setenv('LEXIMIND_DRAFTING_LLM_MODEL','fine-tuned-drafting-v7')
    app=create_app(tmp_path,{'alice':'tenant-a'},start_worker=False,review_engine='extractive')
    try:
        assert app.state.drafting_llm.model=='fine-tuned-drafting-v7'
        assert app.state.review_llm.model!='fine-tuned-drafting-v7'
    finally:app.state.store.close()


def test_drafting_jobs_resume_after_restart(tmp_path):
    app=create_app(tmp_path,{'alice':'tenant-a'},start_worker=False,review_engine='extractive',drafting_llm=DraftModel())
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer alice'
        queued=client.post('/api/v1/drafts',json={'document_type':'notice','jurisdiction':'IN','instructions':'Prepare a notice requesting a response.','facts':{'sender':'Example Sender'}}).json()['data']
    app.state.store.close()
    app=create_app(tmp_path,{'alice':'tenant-a'},review_engine='extractive',drafting_llm=DraftModel())
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer alice'
        assert wait(client,queued['job_id'])['status']=='completed_with_warnings'
        assert client.get('/api/v1/drafts/'+queued['draft_id']).json()['data']['status']=='awaiting_information'
    app.state.store.close()
    app=create_app(tmp_path,{'alice':'tenant-a'},start_worker=False,review_engine='extractive',drafting_llm=DraftModel())
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer alice'
        rid=queued['draft_id'];gaps=client.get(f'/api/v1/drafts/{rid}/requirements').json()['data']['missing_requirement_ids']
        queued=client.post(f'/api/v1/drafts/{rid}/generate',json={'proceed_with_missing_information':True,'acknowledged_requirement_ids':gaps}).json()['data']
    app.state.store.close()
    app=create_app(tmp_path,{'alice':'tenant-a'},review_engine='extractive',drafting_llm=DraftModel())
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer alice'
        assert wait(client,queued['job_id'])['status']=='completed_with_warnings'
        assert client.get('/api/v1/drafts/'+queued['draft_id']).json()['data']['claims']
    app.state.store.close()
