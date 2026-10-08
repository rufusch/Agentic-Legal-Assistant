import json
import time
from io import BytesIO
from uuid import uuid4

import pytest
from docx import Document
from pypdf import PdfReader
from test_common import client, upload, finish
from backend.models.registry import ModelRegistry, SPECS
from backend.models.train import train
from backend.review_schema import verify_report


def review(client, ids, **kwargs):
    response=client.post('/api/v1/reviews',json={'document_ids':ids,**kwargs})
    assert response.status_code==202,response.text
    data=response.json()['data']
    for _ in range(100):
        report=client.get('/api/v1/reviews/'+data['review_id']).json()['data']
        if report['status'] in {'failed','completed_with_warnings','cancelled'}: break
        time.sleep(.05)
    assert report['status']=='completed_with_warnings',report
    return report


def test_review_lifecycle(client):
    ids=[]
    for index,text in enumerate([b'Payment of INR 10,000 is due on 15 October 2026.\nTermination requires 30 days notice.\nAnnexure A is not attached.', b'Payment of INR 20,000 is due on 20 October 2026.\nTermination requires 60 days notice.']):
        data,_=upload(client,text,key=str(index));finish(client,data);ids.append(data['document_id'])
    report=review(client,ids,focus_question='payment termination')
    assert len(report['contradictions'])==3
    assert report['missing_information']
    chunks=client.app.state.store.all('tenant-a','chunk')
    verify_report(report,chunks)
    corrupted=json.loads(json.dumps(report));corrupted['claims'][0]['text']='Invented legal conclusion'
    with pytest.raises(ValueError):verify_report(corrupted,chunks)
    for format in ['json','pdf','docx']:
        response=client.get(f'/api/v1/reviews/{report["id"]}/export?format={format}')
        assert response.status_code==200,response.text
        if format=='pdf': assert 'LexiMind review' in PdfReader(BytesIO(response.content)).pages[0].extract_text()
        if format=='docx': assert Document(BytesIO(response.content)).paragraphs[0].text=='LexiMind review'
    client.headers['Authorization']='Bearer bob'
    assert client.get('/api/v1/reviews/'+report['id']).status_code==404
    assert client.get('/api/v1/reviews').json()['data']['items']==[]
    client.headers['Authorization']='Bearer alice'
    response=client.post('/api/v1/reviews/'+report['id']+'/rerun',json={'focus_question':'notice'})
    assert response.status_code==202
    assert client.get('/api/v1/reviews/'+report['id']).json()['data']==report
    assert len(client.get('/api/v1/reviews/'+report['id']+'/versions').json()['data']['items'])==2
    citation=report['citations'][0]
    annotation={k:citation[k] for k in ['chunk_id','start_offset','end_offset']};annotation['label']='payment'
    path='/api/v1/reviews/'+report['id']+'/feedback'
    assert client.post(path,json={'accepted':True,'annotations':[annotation]}).status_code==201
    assert not client.get('/api/v1/models/review/dataset').text
    assert client.post(path,json={'accepted':True,'use_for_training':True,'annotations':[annotation]}).status_code==201
    assert json.loads(client.get('/api/v1/models/review/dataset').text)['human_approved']
    assert not client.get('/api/v1/models/chat/dataset').text
    client.headers['Authorization']='Bearer bob'
    assert not client.get('/api/v1/models/review/dataset').text
    client.headers['Authorization']='Bearer alice'
    assert client.delete('/api/v1/documents/'+ids[0]).status_code==200
    assert client.get('/api/v1/reviews/'+report['id']).status_code==404
    assert not client.get('/api/v1/models/review/dataset').text


def test_review_validation_and_home(client):
    data,_=upload(client)
    assert client.post('/api/v1/reviews',json={'document_ids':[data['document_id']]}).status_code==409
    assert client.post('/api/v1/reviews',json={'document_ids':[]}).status_code==400
    finish(client,data)
    assert client.post('/api/v1/reviews',json={'document_ids':[data['document_id']],'options':{'compare_with_governing_law':True}}).status_code==422
    report=review(client,[data['document_id']],options={'compare_with_governing_law':True,'jurisdiction':'IN','as_of_date':'2026-10-08'})
    assert any(w['type']=='weak_authority' for w in report['warnings'])
    home=client.get('/api/v1/home').json()['data']
    assert home['tenant']['id']=='tenant-a' and home['recent_activity']
    assert next(w for w in home['workflows'] if w['id']=='review')['available']
    notification=next(n for n in home['notifications'] if n['id']==report['job_id'])
    assert not notification['read']
    assert client.post('/api/v1/notifications/'+notification['id']+'/read').status_code==200
    assert next(n for n in client.get('/api/v1/home').json()['data']['notifications'] if n['id']==notification['id'])['read']
    response=client.post('/api/v1/reviews',json={'document_ids':[data['document_id']]},headers={'Idempotency-Key':'review-once'})
    repeated=client.post('/api/v1/reviews',json={'document_ids':[data['document_id']]},headers={'Idempotency-Key':'review-once'})
    assert response.json()==repeated.json()


def test_review_queue_cancel_and_recovery(tmp_path):
    from backend.app import create_app
    from fastapi.testclient import TestClient
    source_id=str(uuid4())
    app=create_app(tmp_path,{'alice':'tenant-a'},start_worker=False,review_engine='extractive')
    app.state.store.save('tenant-a','document',{'id':source_id,'status':'ready','name':'source.txt','metadata':{},'sha256':'a'*64,'warnings':[]})
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer alice'
        first=c.post('/api/v1/reviews',json={'document_ids':[source_id]}).json()['data']
        assert c.post('/api/v1/jobs/'+first['job_id']+'/cancel').json()['data']['status']=='cancelled'
        assert c.get('/api/v1/reviews/'+first['review_id']).json()['data']['status']=='cancelled'
        second=c.post('/api/v1/reviews',json={'document_ids':[source_id]}).json()['data']
    app.state.store.close()
    app=create_app(tmp_path,{'alice':'tenant-a'},review_engine='extractive')
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer alice'
        for _ in range(100):
            report=c.get('/api/v1/reviews/'+second['review_id']).json()['data']
            if report['status']=='completed_with_warnings':break
            time.sleep(.05)
        assert report['status']=='completed_with_warnings'
        assert any(w['title']=='Insufficient evidence' for w in report['warnings'])
    app.state.store.close()


@pytest.mark.parametrize('workflow',list(SPECS))
def test_separate_trainable_models(workflow,tmp_path):
    records=[{'workflow':workflow,'text':f'{label} example {group} with distinct source wording','label':label,'group_id':str(group),'human_approved':True,'use_for_training':True} for group in range(5) for label in SPECS[workflow][:2]]
    artifact=train(workflow,records,'test-v1',epochs=5,dimension=32)
    path=tmp_path/'model.json';path.write_text(json.dumps(artifact))
    registry=ModelRegistry({workflow:str(path)})
    assert registry.get(workflow).metadata['version']=='test-v1'
    assert registry.get(workflow).classify('source wording')[0] in SPECS[workflow]
    other=next(w for w in SPECS if w!=workflow)
    with pytest.raises(ValueError):ModelRegistry({other:str(path)})
    records[0]['use_for_training']=False
    with pytest.raises(ValueError):train(workflow,records,'invalid')
