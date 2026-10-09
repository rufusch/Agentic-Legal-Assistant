"""Hosted provider wiring: URL/auth per provider, schema fallback, think-tag stripping."""
import json

import httpx
import pytest

from backend.models.review_llm import LocalReviewLLM, _json_from_text

SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok'], 'additionalProperties': False}


def test_local_context_budget_is_sent_to_ollama(monkeypatch):
    monkeypatch.setenv('LEXIMIND_MODEL_CONTEXT_LENGTH','8192')
    calls=[]
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'message':{'content':'{"ok":true}'},'done':True,'done_reason':'stop'})
    model=LocalReviewLLM.for_role('chat',provider='ollama',base_url='http://127.0.0.1:11434',deployment='local',transport=httpx.MockTransport(respond))
    assert model.complete([{'role':'user','content':'test'}],SCHEMA)=={'ok':True}
    assert calls[0]['options']['num_ctx']==8192
    with pytest.raises(ValueError,match='context length'):
        LocalReviewLLM(context_length=100)


def client(respond, **kwargs):
    return LocalReviewLLM(transport=httpx.MockTransport(respond), **kwargs)


def ok(content, provider='groq'):
    calls = []

    def respond(request):
        calls.append({'url': str(request.url), 'headers': request.headers, 'body': json.loads(request.content) if request.content else None})
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': [{'id': 'm'}]})
        if provider == 'anthropic':
            return httpx.Response(200, json={'stop_reason': 'end_turn', 'content': [{'type': 'tool_use', 'input': content}]})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
    return respond, calls


@pytest.mark.parametrize('provider,host,path', [
    ('groq', 'api.groq.com', '/openai/v1/chat/completions'),
    ('openai', 'api.openai.com', '/v1/chat/completions'),
    ('gemini', 'generativelanguage.googleapis.com', '/v1beta/openai/chat/completions'),
    ('openrouter', 'openrouter.ai', '/api/v1/chat/completions'),
])
def test_hosted_presets_resolve_url_and_bearer_auth(provider, host, path):
    respond, calls = ok('{"ok": true}')
    model = client(respond, provider=provider, deployment='cloud', base_url=LocalReviewLLM.for_role('review').base_url if False else __import__('backend.models.review_llm', fromlist=['PRESETS']).PRESETS[provider], model='m', api_key='k')
    assert model.complete([{'role': 'user', 'content': 'q'}], SCHEMA) == {'ok': True}
    assert calls[-1]['url'] == f'https://{host}{path}'
    assert calls[-1]['headers']['authorization'] == 'Bearer k'


def test_anthropic_uses_messages_api_tool_call_and_x_api_key():
    respond, calls = ok({'ok': True}, provider='anthropic')
    model = client(respond, provider='anthropic', deployment='cloud', base_url='https://api.anthropic.com', model='m', api_key='k')
    assert model.complete([{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'q'}], SCHEMA) == {'ok': True}
    body = calls[-1]['body']
    assert calls[-1]['url'] == 'https://api.anthropic.com/v1/messages'
    assert calls[-1]['headers']['x-api-key'] == 'k'
    assert body['system'] == 's' and [m['role'] for m in body['messages']] == ['user']
    assert body['tools'][0]['input_schema'] == SCHEMA


def test_strict_schema_rejection_falls_back_to_json_object_once():
    modes = []

    def respond(request):
        body = json.loads(request.content)
        modes.append(body['response_format']['type'])
        if body['response_format']['type'] == 'json_schema':
            return httpx.Response(400, json={'error': 'response_format.json_schema unsupported'})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok": true}'}}]})
    model = client(respond, provider='groq', deployment='cloud', base_url='https://api.groq.com/openai/v1', model='m', api_key='k')
    assert model.complete([{'role': 'user', 'content': 'q'}], SCHEMA) == {'ok': True}
    assert modes == ['json_schema', 'json_object']


def test_hosted_status_reports_missing_key_without_calling_out():
    called = []

    def respond(request):
        called.append(1)
        return httpx.Response(200, json={'data': []})
    model = client(respond, provider='groq', deployment='cloud', base_url='https://api.groq.com/openai/v1', model='m', api_key='')
    assert model.status()['reason'] == 'MODEL_KEY_MISSING' and not called


def test_auth_and_rate_limit_failures_are_labelled():
    from backend.models.review_llm import ReviewModelError
    for status, code, retryable in [(401, 'MODEL_AUTH_FAILED', False), (429, 'MODEL_RATE_LIMITED', True)]:
        model = client(lambda r, s=status: httpx.Response(s, json={}), provider='groq', deployment='cloud', base_url='https://api.groq.com/openai/v1', model='m', api_key='k')
        with pytest.raises(ReviewModelError) as caught:
            model.complete([{'role': 'user', 'content': 'q'}], SCHEMA)
        assert caught.value.code == code and caught.value.retryable is retryable


@pytest.mark.parametrize('status', [500, 502, 503, 504])
def test_temporary_server_failures_are_retryable(status):
    from backend.models.review_llm import ReviewModelError
    model = client(lambda request: httpx.Response(status, json={}), provider='gemini',
                   deployment='cloud', base_url='https://generativelanguage.googleapis.com/v1beta/openai', model='m')
    with pytest.raises(ReviewModelError) as caught:
        model.complete([{'role': 'user', 'content': 'q'}], SCHEMA)
    assert caught.value.code == 'MODEL_OVERLOADED' and caught.value.retryable


@pytest.mark.parametrize('array_response', [False, True])
def test_gemini_daily_quota_is_not_retryable(array_response):
    from backend.models.review_llm import ReviewModelError
    body = {'error': {'details': [{'violations': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}}
    model = client(lambda request: httpx.Response(429, json=[body] if array_response else body),
                   provider='gemini', deployment='cloud',
                   base_url='https://generativelanguage.googleapis.com/v1beta/openai', model='m')
    with pytest.raises(ReviewModelError) as caught:
        model.complete([{'role': 'user', 'content': 'q'}], SCHEMA)
    assert caught.value.code == 'MODEL_QUOTA_EXHAUSTED' and not caught.value.retryable


@pytest.mark.parametrize('metric', ['tokens per day (TPD)', 'requests per day (RPD)'])
def test_groq_daily_quota_is_not_retryable(metric):
    from backend.models.review_llm import ReviewModelError
    model = client(lambda request: httpx.Response(429, json={'error': {'message': f'Rate limit reached on {metric}.'}}),
                   provider='groq', deployment='cloud', base_url='https://api.groq.com/openai/v1', model='m')
    with pytest.raises(ReviewModelError) as caught:
        model.complete([{'role': 'user', 'content': 'q'}], SCHEMA)
    assert caught.value.code == 'MODEL_QUOTA_EXHAUSTED' and not caught.value.retryable


@pytest.mark.parametrize('raw', ['{"ok": true}', '<think>reasoning</think>{"ok": true}', '```json\n{"ok": true}\n```', 'Here you go:\n{"ok": true}'])
def test_reasoning_prefixes_and_fences_are_stripped(raw):
    assert _json_from_text(raw) == {'ok': True}


def test_role_env_overrides_shared_default(monkeypatch):
    monkeypatch.setenv('LEXIMIND_LLM_PROVIDER', 'groq')
    monkeypatch.setenv('LEXIMIND_LLM_MODEL', 'shared-model')
    monkeypatch.setenv('LEXIMIND_JUDGE_LLM_MODEL', 'judge-model')
    monkeypatch.setenv('GROQ_API_KEY', 'from-provider-env')
    judge, chat = LocalReviewLLM.for_role('judge'), LocalReviewLLM.for_role('chat')
    assert (judge.model, chat.model) == ('judge-model', 'shared-model')
    assert judge.base_url == 'https://api.groq.com/openai/v1' and judge.api_key == 'from-provider-env'
    assert judge.deployment == 'cloud' and judge.metadata['workflow'] == 'judge'
