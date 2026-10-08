import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from scripts.run_codespaces import configure

ROOT = Path(__file__).resolve().parents[1]


def test_forwarded_origin_preserves_explicit_models_and_storage(tmp_path):
    env, origin = configure({'CODESPACE_NAME': 'sample-space',
        'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN': 'app.github.dev',
        'BACKEND_CORS_ORIGINS': 'https://another.example', 'BACKEND_DEMO': '1',
        'BACKEND_STORAGE': str(tmp_path), 'LEXIMIND_CHAT_LLM_MODEL': 'custom-chat',
        'LEXIMIND_VERIFIER_LLM_MODEL': 'custom-verifier'})
    assert origin == 'https://sample-space-8000.app.github.dev'
    assert env['BACKEND_DEMO'] == '0'
    assert env['BACKEND_STORAGE'] == str(tmp_path)
    assert env['LEXIMIND_CHAT_LLM_MODEL'] == 'custom-chat'
    assert env['LEXIMIND_VERIFIER_LLM_MODEL'] == 'custom-verifier'
    assert env['BACKEND_CORS_ORIGINS'].split(',') == ['https://another.example', origin]


def test_invalid_forwarded_hostname_rejected():
    with pytest.raises(ValueError, match='hostname'):
        configure({'CODESPACE_NAME': 'space/invalid', 'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN': 'app.github.dev'})


def test_real_admin_token_accepts_forwarded_origin_without_demo(tmp_path, monkeypatch):
    env, origin = configure({**os.environ, 'BACKEND_STORAGE': str(tmp_path),
        'CODESPACE_NAME': 'test-space', 'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN': 'app.github.dev'})
    result = subprocess.run([sys.executable, '-m', 'backend.admin', '--storage', str(tmp_path),
        'issue-session', '--tenant', 'codespaces-workspace', '--hours', '8'],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    for key in ('BACKEND_CORS_ORIGINS', 'BACKEND_DEMO'):
        monkeypatch.setenv(key, env[key])
    from backend.app import create_app
    app = create_app(storage=tmp_path, start_worker=False)
    with TestClient(app, base_url=origin) as client:
        assert client.post('/demo/session').status_code == 404
        assert client.get('/api/v1/session').status_code == 401
        headers = {'Authorization': 'Bearer ' + result.stdout.strip(), 'Origin': origin}
        assert client.get('/api/v1/session', headers=headers).status_code == 200
        body = {'file_name': 'source.txt', 'content_type': 'text/plain', 'size_bytes': 1, 'sha256': '0' * 64}
        assert client.post('/api/v1/documents/uploads', headers=headers, json=body).status_code == 201
        headers['Origin'] = 'https://foreign.example'
        assert client.post('/api/v1/documents/uploads', headers=headers, json=body).status_code == 403
    app.state.store.close()


def test_devcontainer_paths_and_linux_line_endings():
    cfg = json.loads((ROOT / '.devcontainer/devcontainer.json').read_text())
    assert 8000 in cfg['forwardPorts']
    for name in ('scripts/setup-codespaces.sh', 'scripts/start-codespaces.sh', '.devcontainer/Dockerfile'):
        assert b'\r\n' not in (ROOT / name).read_bytes()
    assert cfg['image'] == 'mcr.microsoft.com/devcontainers/python:1-3.12-bookworm'
    assert 'build' not in cfg
