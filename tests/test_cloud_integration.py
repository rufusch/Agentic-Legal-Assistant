import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.models.review_llm import LocalReviewLLM


def test_cloud_model_secret_and_schema_transport():
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]})
    model = LocalReviewLLM(provider='compatible', deployment='cloud', base_url='https://models.example', api_key='test-secret', model='review-trained-v3', transport=httpx.MockTransport(respond))
    assert model.complete([], {'type': 'object'}) == {'ok': True}
    assert seen[0].headers['authorization'] == 'Bearer test-secret'
    assert seen[0].url.path == '/v1/chat/completions'
    assert json.loads(seen[0].content)['response_format']['type'] == 'json_schema'
    assert 'test-secret' not in repr(model) + json.dumps(model.metadata)
    assert model.metadata['kind'] == 'hosted_llm'


def test_private_model_network_requires_explicit_configuration():
    with pytest.raises(ValueError):
        LocalReviewLLM(deployment='cloud', base_url='http://model:11434')
    assert LocalReviewLLM(deployment='cloud', base_url='http://model:11434', allow_private_http=True).metadata['deployment'] == 'cloud'
    with pytest.raises(ValueError):
        LocalReviewLLM(deployment='cloud', base_url='https://user:secret@models.example')


def test_separate_spa_preflight_auth_and_origin(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKEND_CORS_ORIGINS', 'https://frontend.example,http://localhost:5173')
    app = create_app(tmp_path, {'alice': 'tenant-a'}, start_worker=False, review_engine='extractive')
    try:
        with TestClient(app) as client:
            response = client.options('/api/v1/documents/uploads', headers={'Origin': 'https://frontend.example', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,idempotency-key,content-type,last-event-id'})
            assert response.status_code == 200
            assert response.headers['access-control-allow-origin'] == 'https://frontend.example'
            response = client.get('/api/v1/session', headers={'Origin': 'https://frontend.example'})
            assert response.status_code == 401
            assert response.headers['access-control-allow-origin'] == 'https://frontend.example'
            headers = {'Authorization': 'Bearer alice', 'Origin': 'https://frontend.example'}
            # Invalid body reaches endpoint validation rather than origin rejection.
            response = client.post('/api/v1/reviews', json={}, headers=headers)
            assert response.status_code == 400
            assert response.json()['error']['code'] == 'VALIDATION_ERROR'
            headers['Origin'] = 'https://untrusted.example'
            assert client.post('/api/v1/reviews', json={}, headers=headers).status_code == 403
    finally:
        app.state.store.close()
