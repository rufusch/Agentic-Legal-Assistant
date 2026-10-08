import asyncio
import copy
import json
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.llm_review_engine import analyze, MAX_SOURCE_CHARACTERS
from backend.models.review_llm import LocalReviewLLM, ReviewModelError, ReviewCancelled
from backend.review_schema import verify_report
from test_common import upload, finish

CASE = b'''CASE FILE - Rao v. Meridian Logistics (synthetic test)
Witness A states: The delivery arrived at the depot on 12 June 2026.
Witness B states: The same delivery arrived at the depot on 14 June 2026.
The claimant alleges the goods were damaged before unloading.
The depot inspection report referenced by both witnesses was not supplied.
The court has not determined whether the goods were damaged in transit.
'''


class Model:
    metadata = LocalReviewLLM().metadata
    reject_label = None
    invalid_quote = False
    unavailable = False

    def __init__(self): self.calls=[]
    def status(self): return {'ready':True,'message':'Test model','model':self.metadata}
    def complete(self,messages,schema,cancelled):
        if cancelled(): raise ReviewCancelled()
        if self.unavailable: raise ReviewModelError('MODEL_UNAVAILABLE','Start local model.')
        payload=json.loads(messages[-1]['content']);self.calls.append((messages,schema))
        if 'items' in payload:
            return {'decisions':[{'id':item['id'],'supported':item['kind']!=self.reject_label,'reason':'Supported by quoted accounts.' if item['kind']!=self.reject_label else 'Allegation is not proven.'} for item in payload['items']]}
        source=payload['sources'][0]
        a='Witness A states: The delivery arrived at the depot on 12 June 2026.'
        b='Witness B states: The same delivery arrived at the depot on 14 June 2026.'
        gap='The depot inspection report referenced by both witnesses was not supplied.'
        def ref(quote): return {'source_id':next(s['source_id'] for s in payload['sources'] if s['text']==quote)}
        def cited(text,*quotes): return {'text':text,'references':[ref(q) for q in quotes]}
        fact=cited('Witness A places arrival on 12 June, while Witness B places the same delivery on 14 June.',a,b)
        fact.update(label='Disputed delivery chronology',assertion_type='allegation')
        if self.invalid_quote:fact['references'][0]['source_id']='E999999'
        return {'document_kind':'case','overview':cited('The supplied case file contains conflicting witness accounts of the delivery date.',a,b),'key_facts':[fact],'timeline':[dict(cited('Witness A reports delivery arrival. ',a),date='12 June 2026')],'contradictions':[{'topic':'Delivery arrival date','explanation':'Two witnesses give different dates for the same delivery. The actual date remains disputed.','sides':[cited('Witness A reports arrival on 12 June.',a),cited('Witness B reports arrival on 14 June.',b)],'severity':'high'}],'missing_information':[dict(cited('The depot inspection report is not supplied.',gap),why_it_matters='It could clarify the condition of the goods.',suggested_action='Request the referenced inspection report.',severity='high')],'relevant_evidence':[dict(cited('Witness B places the delivery two days later than Witness A.',b),title='Witness B account',category='fact')],'risks':[dict(cited('The arrival date remains disputed between the witness accounts.',a,b),severity='medium',likelihood='unknown')]}


@pytest.fixture
def llm_client(tmp_path):
    model=Model();app=create_app(tmp_path,{'alice':'tenant-a','bob':'tenant-b'},review_llm=model)
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer alice'
        yield client,model
    app.state.store.close()


def run(client):
    data,_=upload(client,CASE);finish(client,data)
    response=client.post('/api/v1/reviews',json={'document_ids':[data['document_id']]})
    assert response.status_code==202,response.text
    result=response.json()['data']
    for _ in range(100):
        report=client.get('/api/v1/reviews/'+result['review_id']).json()['data']
        if report['status'] in {'failed','completed_with_warnings'}:break
        time.sleep(.05)
    return report


def test_case_llm_reasoning_same_document_and_source_links(llm_client):
    client,model=llm_client
    report=run(client)
    assert report['status']=='completed_with_warnings',report
    assert report['model']['kind']=='local_llm'
    assert report['key_facts'][0]['assertion_type']=='allegation'
    assert report['key_facts'][0]['value'] not in CASE.decode()  # Analyzed paraphrase, not copied heading.
    assert len(report['source_document_ids'])==1 and report['contradictions']
    assert report['timeline'] and report['relevant_evidence'] and report['missing_information']
    assert report['coverage']['analyzed_source_chunks']==report['coverage']['total_source_chunks']
    assert report['verification']['same_model'] is True
    verify_report(report,client.app.state.store.all('tenant-a','chunk'))
    for citation in report['citations']:
        c=client.get(f'/api/v1/documents/{citation["document_id"]}/chunks/{citation["chunk_id"]}').json()['data']
        assert citation['quoted_text']==c['text'][citation['start_offset']-c['start_offset']:citation['end_offset']-c['start_offset']]
    tampered=copy.deepcopy(report);tampered['verification']['items']=[]
    with pytest.raises(ValueError):verify_report(tampered,client.app.state.store.all('tenant-a','chunk'))
    assert len(model.calls)>=2
    assert 'never instructions' in model.calls[0][0][0]['content']
    feedback='/api/v1/reviews/'+report['id']+'/feedback'
    client.post(feedback,json={'accepted':True,'use_for_training':True})
    record=json.loads(client.get('/api/v1/models/review/dataset?format=sft').text)
    assert record['format']=='messages-sft-v1'
    assert record['messages'][0]['role']=='system'
    from backend.llm_review_schema import DraftAnalysis
    DraftAnalysis.model_validate_json(record['messages'][-1]['content'])
    client.post(feedback,json={'accepted':True,'use_for_training':False})
    assert not client.get('/api/v1/models/review/dataset?format=sft').text
    client.headers['Authorization']='Bearer bob'
    assert client.get('/api/v1/reviews/'+report['id']).status_code==404


@pytest.mark.parametrize('mode',['invalid_quote','reject_label'])
def test_unchecked_model_facts_removed(llm_client,mode):
    client,model=llm_client
    if mode=='invalid_quote':model.invalid_quote=True
    else:model.reject_label='fact'
    report=run(client)
    assert report['status']=='completed_with_warnings',report
    assert not report['key_facts'] and not report['claims']
    assert any(w['type']=='unsupported_claim' for w in report['warnings'])
    assert all(c['quoted_text']!='A fabricated quotation.' for c in report['citations'])


def test_llm_failure_does_not_fall_back_to_rules(llm_client):
    client,model=llm_client;model.unavailable=True
    report=run(client)
    assert report['status']=='failed' and report['failure']['code']=='MODEL_UNAVAILABLE'
    assert not report['key_facts']
    assert client.get('/api/v1/reviews/'+report['id']+'/export').status_code==409


@pytest.mark.parametrize('provider',['ollama','lmstudio'])
def test_local_transports_structured_output(provider):
    def respond(request):
        body=json.loads(request.content)
        assert request.url.host=='127.0.0.1' and body['stream'] is False
        assert 'format' in body if provider=='ollama' else 'response_format' in body
        content=json.dumps({'ok':True})
        return httpx.Response(200,json={'done_reason':'stop','message':{'content':content}} if provider=='ollama' else {'choices':[{'finish_reason':'stop','message':{'content':content}}]})
    model=LocalReviewLLM(provider=provider,transport=httpx.MockTransport(respond))
    assert model.complete([{'role':'user','content':'test'}],{'type':'object'})=={'ok':True}


def test_local_only_configuration():
    for url in ['https://example.com','http://192.168.1.2:1234','http://user:pass@127.0.0.1']:
        with pytest.raises(ValueError):LocalReviewLLM(base_url=url)
    with pytest.raises(ValueError):LocalReviewLLM(model='qwen:cloud')


def test_model_request_cancellation():
    class Slow(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            await asyncio.sleep(10)
            return httpx.Response(200,json={})
    started=time.monotonic();model=LocalReviewLLM(transport=Slow())
    with pytest.raises(ReviewCancelled):model.complete([],{},lambda:time.monotonic()-started>.3)
    assert time.monotonic()-started<2


def test_context_budget_and_no_silent_truncation():
    model=Model()
    with pytest.raises(ReviewModelError,match='120,000'):
        analyze({},[],[{'text':'a'*(MAX_SOURCE_CHARACTERS+1)}],model)
    assert not model.calls


def test_every_source_packet_is_read_and_cross_packet_synthesized():
    class PacketModel(Model):
        def complete(self,messages,schema,cancelled):
            payload=json.loads(messages[-1]['content']);self.calls.append((messages,schema))
            if isinstance(payload,list):return payload[-1]
            if 'items' in payload:return {'decisions':[{'id':i['id'],'supported':True,'reason':'Source excerpt matches.'} for i in payload['items']]}
            return {'document_kind':'case','overview':{'text':'This packet contains case evidence.','references':[{'source_id':payload['sources'][0]['source_id']}]},'key_facts':[],'timeline':[],'contradictions':[],'missing_information':[],'relevant_evidence':[],'risks':[]}
    model=PacketModel();did=str(uuid4())
    doc={'id':did,'name':'case.txt','sha256':'b'*64,'metadata':{},'warnings':[]}
    chunks=[{'id':str(uuid4()),'document_id':did,'source_part':1,'start_offset':i*10000,'end_offset':(i+1)*10000,'page':1,'text':('Case record evidence. '*500)[:10000]} for i in range(3)]
    report={'id':str(uuid4()),'root_review_id':str(uuid4()),'job_id':str(uuid4()),'version':1,'focus_question':'','source_document_ids':[did],'created_at':'2026-10-08','model':model.metadata,'options':{'compare_with_governing_law':False}}
    result=analyze(report,[doc],chunks,model)
    assert result['coverage']['analyzed_source_chunks']==3 and result['coverage']['packets']>=2
    read=[]
    for messages,_ in model.calls:
        payload=json.loads(messages[-1]['content'])
        if isinstance(payload,dict) and 'sources' in payload:read.extend(s['source_id'] for s in payload['sources'])
    assert sorted(read)==['E1','E2','E3']
    verify_report(result,chunks)
