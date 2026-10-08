from uuid import uuid4
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.grounding import inspect,material_values_supported
from tests.test_common import upload,finish
from tests.test_reviews import review


def test_values_and_empty_scores():
    assert material_values_supported('INR 5,000.00',['INR 5000'])
    assert not material_values_supported('INR9000',['INR 5000'])
    assert not material_values_supported('Section 999',['Section 73'])
    result=inspect({'id':'empty','status':'completed','claims':[],'citations':[]},lambda d,c:None)
    assert result['traceability_score'] is None and not result['source_integrity_passed'] and result['abstained']


def test_invalid_spans_and_stale_edit_verification():
    cid=str(uuid4());claim={'id':str(uuid4()),'text':'Payment is 5000.','citation_ids':[cid],'verification_status':'partially_supported'}
    citation={'id':cid,'document_id':'doc','chunk_id':'chunk','quoted_text':'Payment is 5000.','start_offset':0,'end_offset':16}
    source={'document_id':'doc','text':'Payment is 5000.','start_offset':0}
    result={'id':'draft','status':'completed','claims':[claim],'citations':[citation]}
    assert inspect(result,lambda d,c:source)['source_integrity_passed']
    result['needs_verification']=True
    assert not inspect(result,lambda d,c:source)['source_integrity_passed']
    citation['start_offset']=1
    assert not inspect(result,lambda d,c:source)['claims'][0]['source_integrity']


def test_audit_real_review_source_ownership_and_export(tmp_path):
    app=create_app(tmp_path,{'a':'tenant-a','b':'tenant-b'},review_engine='extractive')
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer a';ticket,_=upload(c);finish(c,ticket)
        result=review(c,[ticket['document_id']])
        query=f'?workflow=review&resource_id={result["id"]}'
        audited=c.get('/api/v1/grounding-audit'+query)
        assert audited.status_code==200,audited.text
        assert audited.json()['data']['traceable_claims']>=len(result['claims'])
        assert c.get('/api/v1/grounding-audit/export'+query).json()['resource_id']==result['id']
        assert c.get('/api/v1/grounding-audit/outputs').json()['data']['items']
        c.headers['Authorization']='Bearer b'
        assert c.get('/api/v1/grounding-audit'+query).status_code==404
        assert not c.get('/api/v1/grounding-audit/outputs').json()['data']['items']
    app.state.store.close()


def test_starter_sources_are_public_and_hashed(tmp_path):
    import hashlib
    app=create_app(tmp_path,{'a':'tenant-a'},start_worker=False,review_engine='extractive')
    with TestClient(app) as c:
        assert c.get('/api/v1/starter-corpus').status_code==401
        c.headers['Authorization']='Bearer a'
        sources=c.get('/api/v1/starter-corpus').json()['data']['items']
        assert len(sources)==2
        for source in sources:
            response=c.get(source['download_url']);assert response.content.startswith(b'%PDF')
            assert hashlib.sha256(response.content).hexdigest()==source['sha256']
        assert c.get('/public-sources/local.key').status_code==404
    app.state.store.close()
def test_verification_schema_bounds_exact_input_ids():
    from backend.models.review_llm import verification_schema
    from backend.research_schema import Checks
    from uuid import uuid4
    ids=[str(uuid4()),str(uuid4())]
    schema=verification_schema(Checks,[{'id':i} for i in ids])
    assert schema['properties']['decisions']['minItems']==2
    assert schema['properties']['decisions']['maxItems']==2
    assert schema['$defs']['Decision']['properties']['id']['enum']==ids
    assert 'enum' not in Checks.model_json_schema()['$defs']['Decision']['properties']['id']
