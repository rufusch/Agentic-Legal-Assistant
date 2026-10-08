import hashlib
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.parsing import chunks
from test_common import client, finish, upload


def test_hybrid_search_exact_sources_and_filters(client):
    first, _ = upload(client, b'PAYMENT\nPayment of INR 150000 is due on 15 October.\nTermination requires notice.')
    finish(client, first)
    second, _ = upload(client, b'Delivery of goods is due in December.', 'second')
    finish(client, second)
    response = client.post('/api/v1/documents/search', json={'query': 'payment October', 'jurisdiction': 'IN'})
    assert response.status_code == 200, response.text
    result = response.json()['data']
    assert result['items'][0]['citation']['document_id'] == first['document_id']
    assert result['items'][0]['lexical_score'] > 0
    assert result['items'][0]['dense_score'] > 0
    citation = result['items'][0]['citation']
    source = client.get(f"/api/v1/documents/{citation['document_id']}/chunks/{citation['chunk_id']}").json()['data']
    assert citation['quoted_text'] == source['text']
    assert client.post('/api/v1/documents/search', json={'query': 'payment', 'jurisdiction': 'US'}).json()['data']['items'] == []
    assert client.post('/api/v1/documents/search', json={'query': 'payment'}, headers={'Authorization': 'Bearer bob'}).json()['data']['items'] == []
    assert client.post('/api/v1/documents/search', json={'query': 'payment', 'document_ids': [first['document_id']]}, headers={'Authorization': 'Bearer bob'}).status_code == 404


def test_delete_cascades_and_stale_replay_is_removed(client):
    data, body = upload(client)
    result = finish(client, data)
    chunks = client.get(f"/api/v1/documents/{data['document_id']}/chunks").json()['data']['items']
    assert client.delete(f"/api/v1/documents/{data['document_id']}", headers={'Authorization': 'Bearer bob'}).status_code == 404
    assert client.delete(f"/api/v1/documents/{data['document_id']}").json()['data']['deleted']
    assert client.get(f"/api/v1/jobs/{result['job_id']}").status_code == 404
    assert client.get(f"/api/v1/documents/{data['document_id']}/chunks/{chunks[0]['id']}").status_code == 404
    assert not list(client.app.state.store.root.glob('*.blob'))
    replay = client.post('/api/v1/documents/uploads', json=body, headers={'Idempotency-Key': 'upload-1'}).json()['data']
    assert replay['document_id'] != data['document_id']


def test_dedup_preserves_independent_provenance(client):
    first, _ = upload(client)
    finish(client, first)
    second, _ = upload(client, key='second')
    finish(client, second)
    doc = client.get(f"/api/v1/documents/{second['document_id']}").json()['data']
    assert doc['deduplicated_from'] == first['document_id']
    a = client.get(f"/api/v1/documents/{first['document_id']}/chunks").json()['data']['items'][0]
    b = client.get(f"/api/v1/documents/{second['document_id']}/chunks").json()['data']['items'][0]
    assert a['text'] == b['text'] and a['id'] != b['id']
    client.delete(f"/api/v1/documents/{first['document_id']}")
    assert client.get(f"/api/v1/documents/{second['document_id']}/chunks/{b['id']}").status_code == 200


def test_sessions_expire_revoke_and_rate_limit(tmp_path):
    app = create_app(tmp_path, {}, start_worker=False, rate_limit=3)
    with TestClient(app) as c:
        expired = app.state.issue_session('t', -1)
        assert c.get('/api/v1/home', headers={'Authorization': 'Bearer ' + expired}).status_code == 401
        token = app.state.issue_session('t')
        c.headers['Authorization'] = 'Bearer ' + token
        assert c.get('/api/v1/home').status_code == 200
        assert c.post('/api/v1/session/revoke').status_code == 200
        assert c.get('/api/v1/home').status_code == 401
        token = app.state.issue_session('t')
        c.headers['Authorization'] = 'Bearer ' + token
        assert [c.get('/api/v1/home').status_code for _ in range(4)] == [200, 200, 200, 429]
    app.state.store.close()


def test_local_session_is_opt_in_and_origin_restricted(tmp_path):
    app = create_app(tmp_path, {}, demo=True, start_worker=False)
    with TestClient(app, base_url='http://127.0.0.1') as c:
        assert c.post('/demo/session', headers={'Origin': 'http://evil.example'}).status_code == 403
        assert c.post('/demo/session', headers={'Host': 'public.example'}).status_code == 404
        token = c.post('/demo/session').json()['data']['token']
        assert c.get('/api/v1/home', headers={'Authorization': 'Bearer '+token}).status_code == 200
        assert c.post('/api/v1/documents/search', json={'query':'payment'}, headers={'Authorization':'Bearer '+token,'Origin':'http://evil.example'}).status_code == 403
        assert c.get('/').status_code == 200
        assert 'frame-ancestors' in c.get('/').headers['Content-Security-Policy']
        assert c.get('/static/app.js').status_code == 200
    app.state.store.close()


def test_retention_cascades(client):
    data, _ = upload(client)
    result = finish(client, data)
    store = client.app.state.store
    doc = store.get('tenant-a', 'document', data['document_id'])
    doc['retention_expires_at'] = time.time() - 1
    store.save('tenant-a', 'document', doc)
    client.app.state.worker.cleanup()
    assert client.get(f"/api/v1/documents/{data['document_id']}").status_code == 404
    assert client.get(f"/api/v1/jobs/{result['job_id']}").status_code == 404


@pytest.mark.parametrize('extension,media_type', [('png','image/png'), ('pdf','application/pdf')])
def test_real_scanned_document_ocr(client, extension, media_type):
    source = Path(__file__).resolve().parent.parent / 'frontend' / 'samples' / ('scanned-annexure.' + extension)
    raw = source.read_bytes()
    body = {'file_name': source.name, 'content_type': media_type, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    data = client.post('/api/v1/documents/uploads', json=body).json()['data']
    client.put(data['upload_url'], content=raw)
    result = finish(client, data)
    doc = client.get(f"/api/v1/documents/{data['document_id']}").json()['data']
    assert doc['status'] == 'ready', doc
    assert doc['ocr_used'] and doc['warnings']
    assert client.get(f"/api/v1/jobs/{result['job_id']}").json()['data']['status'] == 'completed_with_warnings'
    passages = client.get(f"/api/v1/documents/{data['document_id']}/chunks").json()['data']['items']
    assert 'DELIVERY' in ''.join(c['text'] for c in passages).upper()
    matches = client.post('/api/v1/documents/search', json={'query':'delivery payment', 'document_ids':[data['document_id']]}).json()['data']['items']
    assert matches and matches[0]['citation']['document_id'] == data['document_id']


def test_structure_chunks_cover_source_exactly():
    text = '1. PAYMENT\n' + ('Payment due on 15 October.\n\n' * 150)
    result = list(chunks(text))
    assert ''.join(c[2] for c in result) == text
    assert all(text[start:end] == part and len(part) <= 1200 for start,end,part in result)


def test_queued_cancel_retry_and_recovery(tmp_path):
    app = create_app(tmp_path, {'alice':'tenant-a'}, start_worker=False)
    with TestClient(app, headers={'Authorization':'Bearer alice'}) as c:
        data,_ = upload(c)
        result=finish(c,data)
        c.post(f"/api/v1/jobs/{result['job_id']}/cancel")
        retry = c.post(f"/api/v1/documents/{data['document_id']}/retry", headers={'Idempotency-Key':'retry'}).json()['data']
        assert retry['job_id'] != result['job_id']
        assert c.post(f"/api/v1/documents/{data['document_id']}/retry", headers={'Idempotency-Key':'retry'}).json()['data'] == retry
    app.state.store.close()
    restored = create_app(tmp_path, {'alice':'tenant-a'})
    with TestClient(restored, headers={'Authorization':'Bearer alice'}) as c:
        for _ in range(200):
            job = c.get(f"/api/v1/jobs/{retry['job_id']}").json()['data']
            if job['status'] in {'completed','failed'}: break
            time.sleep(.1)
        assert job['status'] == 'completed'
    restored.state.store.close()


def test_running_parser_cancels_without_publishing(tmp_path):
    import threading
    started = threading.Event()
    app = create_app(tmp_path, {'alice':'tenant-a'})
    def parsing(raw, media_type, cancelled):
        started.set()
        for _ in range(300):
            if cancelled(): return {'cancelled':True}
            time.sleep(.01)
        raise RuntimeError('test parser should have been cancelled')
    app.state.worker.parser = parsing
    with TestClient(app, headers={'Authorization':'Bearer alice'}) as c:
        data,_ = upload(c)
        result = c.post(f"/api/v1/documents/{data['document_id']}/complete",json={'upload_id':data['upload_id']}).json()['data']
        assert started.wait(3)
        assert c.post(f"/api/v1/jobs/{result['job_id']}/cancel").json()['data']['status'] == 'cancelled'
        time.sleep(.1)
        assert not app.state.store.all('tenant-a','chunk')
        assert c.get(f"/api/v1/jobs/{result['job_id']}").json()['data']['status'] == 'cancelled'
    app.state.store.close()


def test_mutation_failure_rolls_back_all_resources(tmp_path, monkeypatch):
    app = create_app(tmp_path, {'alice':'tenant-a'}, start_worker=False)
    with TestClient(app, headers={'Authorization':'Bearer alice'},raise_server_exceptions=False) as c:
        data,_ = upload(c)
        def fail(*args, **kwargs): raise RuntimeError('injected audit failure')
        monkeypatch.setattr(app.state.store,'audit',fail)
        response = c.post(f"/api/v1/documents/{data['document_id']}/complete",json={'upload_id':data['upload_id']},headers={'Idempotency-Key':'failed-complete'})
        assert response.status_code == 500
        assert response.json()['error']['code'] == 'INTERNAL_ERROR'
        assert c.get(f"/api/v1/documents/{data['document_id']}").json()['data']['status'] == 'uploading'
        assert not app.state.store.all('tenant-a','job')
        assert app.state.db.execute('SELECT COUNT(*) FROM queue').fetchone()[0] == 0
    app.state.store.close()


def test_second_worker_for_same_storage_is_rejected(tmp_path):
    app=create_app(tmp_path, {})
    second=create_app(tmp_path,{})
    with TestClient(app):
        with pytest.raises(RuntimeError,match='already has a worker'):
            with TestClient(second): pass
    app.state.store.close()
    second.state.store.close()
