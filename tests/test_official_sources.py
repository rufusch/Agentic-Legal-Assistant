import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend import official_sources as official
from backend.storage import Store
from tests.test_research import ResearchModel, wait


@pytest.mark.parametrize('url',['http://api.sci.gov.in/a.pdf','https://api.sci.gov.in.evil.com/a.pdf',
    'https://user:pass@api.sci.gov.in/a.pdf','https://127.0.0.1/a.pdf','https://api.sci.gov.in:8443/a.pdf',
    'https://example.com/a.pdf','https://api.sci.gov.in/a.pdf#instructions'])
def test_reject_untrusted_source_urls(url):
    with pytest.raises(official.OfficialSourceError):official.validate_url(url)


def test_redirect_is_validated_before_network(monkeypatch):
    calls=[]
    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(302,headers={'location':'https://127.0.0.1/secrets'})
    client=httpx.Client
    monkeypatch.setattr(official.socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('8.8.8.8',443))])
    monkeypatch.setattr(official.httpx,'Client',lambda **kw:client(transport=httpx.MockTransport(handle),**kw))
    with pytest.raises(official.OfficialSourceError):official.fetch('https://api.sci.gov.in/test.pdf')
    assert calls==['https://api.sci.gov.in/test.pdf']


def test_private_dns_is_rejected(monkeypatch):
    monkeypatch.setattr(official.socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('10.0.0.1',443))])
    with pytest.raises(official.OfficialSourceError,match='non-public'):official.validate_url('https://api.sci.gov.in/a',resolve=True)


def parsed(*args):
    return {'result':{'pages':[{'number':1,'text':'Test statute: the authority shall provide an opportunity of hearing.\n','ocr':False}],
            'warnings':[],'parser_version':'test'}}


def test_official_import_research_cites_original_and_is_tenant_scoped(tmp_path,monkeypatch):
    monkeypatch.setenv('LEXIMIND_OFFICIAL_SOURCES','1')
    url='https://www.indiacode.nic.in/hearing.pdf';raw=b'%PDF-test official bytes'
    monkeypatch.setattr(official,'fetch',lambda u:(raw,url))
    monkeypatch.setattr(official,'catalog',lambda:[{'title':'Hearing statute','url':url,'document_type':'statute','keywords':'hearing'}])
    app=create_app(tmp_path,{'a':'tenant-a','b':'tenant-b'},review_engine='extractive',research_llm=ResearchModel())
    app.state.worker.parser=parsed
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer a'
        ticket=c.post('/api/v1/research',json={'question':'Does the statute provide a hearing?'}).json()['data']
        assert wait(c,ticket['job_id'])['status']=='completed_with_warnings'
        memo=c.get('/api/v1/research/'+ticket['research_id']).json()['data']
        assert memo['claims'] and memo['citations'][0]['source_url']==url,memo
        assert memo['citations'][0]['source_sha256']==hashlib.sha256(raw).hexdigest()
        assert memo['retrieval']['official_sources']['sources'][0]['retrieval_mode']=='live_official_pdf'
        from io import BytesIO
        from zipfile import ZipFile
        exported=c.get('/api/v1/research/'+ticket['research_id']+'/export?format=docx')
        assert exported.status_code==200
        assert url.encode() in ZipFile(BytesIO(exported.content)).read('word/document.xml')
        rid=memo['citations'][0]['document_id']
        assert app.state.official_sources.verified('tenant-a',app.state.store.get('tenant-a','document',rid))
        c.headers['Authorization']='Bearer b'
        assert c.get('/api/v1/documents/'+rid).status_code==404
        forged={'id':'forged','sha256':hashlib.sha256(raw).hexdigest(),'metadata':{'official_verified':True,'source_url':url}}
        assert not app.state.official_sources.verified('tenant-b',forged)
    app.state.store.close()


def test_dated_snapshot_and_hash_are_explicit(tmp_path,monkeypatch):
    monkeypatch.setattr(official,'fetch',lambda u:(_ for _ in ()).throw(official.OfficialSourceError('Site unavailable')))
    store=Store(tmp_path);service=official.OfficialSources(store,SimpleNamespace(parser=parsed))
    url='https://www.indiacode.nic.in/bitstream/123456789/2187/2/A187209.pdf'
    doc=service.import_source('a',url,'Contract Act','statute')
    assert doc['metadata']['retrieval_mode']=='dated_official_snapshot'
    assert doc['metadata']['snapshot_date']=='2026-10-08'
    assert doc['metadata']['live_fetch_failure']=='Site unavailable'
    assert service.verified('a',doc)
    store.close()


def test_unavailable_source_is_never_imported(tmp_path,monkeypatch):
    monkeypatch.setattr(official,'fetch',lambda u:(_ for _ in ()).throw(official.OfficialSourceError('Site unavailable')))
    store=Store(tmp_path);service=official.OfficialSources(store,SimpleNamespace(parser=parsed))
    with pytest.raises(official.OfficialSourceError):service.import_source('a','https://api.sci.gov.in/missing.pdf','Missing case','judgment')
    assert not store.all('a','document') and not store.all('a','chunk')
    store.close()
