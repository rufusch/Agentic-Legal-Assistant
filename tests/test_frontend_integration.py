from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import create_app

def test_integrated_frontend_and_preserved_backend_preview(tmp_path):
    app=create_app(tmp_path,{'test-token':'tenant'},start_worker=False,review_engine='extractive')
    with TestClient(app) as c:
        page=c.get('/')
        assert page.status_code==200 and 'CaseLens' in page.text and 'js/app.js' in page.text
        assert c.get('/js/app.js').status_code==200
        assert 'initializeSession' in c.get('/js/app.js').text
        assert c.get('/css/design-system.css').status_code==200
        assert 'LexiMind' in c.get('/backend-preview').text
        assert c.get('/js/api/mock-backend.js').status_code==404
        assert c.get('/api/v1/documents').status_code==401
    app.state.store.close()

def test_active_frontend_modules_have_no_fixture_backends():
    root=Path(__file__).resolve().parents[1]/'hacknex2-frontend'/'js'
    for file in root.rglob('*.js'):
        text=file.read_text(encoding='utf-8')
        assert 'mock-backend.js' not in text
        assert 'TENANT_DATA' not in text
