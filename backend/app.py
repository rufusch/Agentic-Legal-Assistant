import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException

from backend.jobs import TERMINAL, Worker
from backend.retrieval import search
from backend.storage import Store

BASE = Path(__file__).resolve().parent.parent
TYPES = {'application/msword', 'text/plain', 'application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'image/png', 'image/jpeg', 'image/tiff'}


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class Upload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0, le=25 * 1024 * 1024)
    sha256: str = Field(pattern=r'^[a-fA-F0-9]{64}$')


class Complete(BaseModel):
    model_config = ConfigDict(extra='forbid')
    upload_id: UUID
    metadata: dict = Field(default_factory=dict)


class Search(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=2, max_length=2000)
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    jurisdiction: str | None = Field(default=None, max_length=100)
    document_type: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=10, ge=1, le=30)


class APIError(Exception):
    def __init__(self, status, code, message, retryable=False):
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


def create_app(storage=None, tokens=None, encryption_key=None, *, start_worker=True, demo=None, rate_limit=240, review_engine=None, review_llm=None, drafting_llm=None, research_llm=None, chat_llm=None, verify_llm=None):
    s = Store(storage or os.getenv('BACKEND_STORAGE', '.data'), encryption_key or os.getenv('BACKEND_ENCRYPTION_KEY'))
    auth = tokens if tokens is not None else json.loads(os.getenv('BACKEND_TOKENS', '{}'))
    demo = os.getenv('BACKEND_DEMO') == '1' if demo is None else demo
    # Derive only this Codespace's exact origin, including when started directly
    # with uvicorn instead of the wrapper. Never trust arbitrary forwarded hosts.
    from scripts.run_codespaces import configure
    deployment_env, _ = configure(os.environ)
    cors_origins = [x.strip().rstrip('/') for x in deployment_env.get('BACKEND_CORS_ORIGINS','').split(',') if x.strip()]
    if any(x=='*' or not x.startswith(('https://','http://')) for x in cors_origins):
        raise ValueError('Specify exact frontend origins in BACKEND_CORS_ORIGINS.')
    signing, startup = secrets.token_bytes(32), time.time()
    retention = int(os.getenv('BACKEND_RETENTION_DAYS', '30'))
    if retention < 1:
        raise ValueError('Retention must be at least one day.')
    worker, attempts = Worker(s, retention), defaultdict(deque)

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            worker.start()
        try:
            yield
        finally:
            await asyncio.to_thread(worker.close)

    app = FastAPI(title='Hacknex shared backend', version='1.1.0', lifespan=lifespan)
    app.state.db, app.state.store, app.state.worker = s.db, s, worker

    def get(tenant, kind, rid):
        item = s.get(tenant, kind, rid)
        if item is None:
            raise APIError(404, 'NOT_FOUND', 'Resource unavailable.')
        return item

    def envelope(request, data):
        return {'data': data, 'meta': {'request_id': request.state.request_id, 'api_version': 'v1'}}

    def error(request, status, code, message, retryable=False, fields=None):
        return JSONResponse({'error': {'code': code, 'message': message, 'field_errors': fields or [], 'retryable': retryable, 'request_id': request.state.request_id}}, status_code=status)

    def issue_session(tenant, seconds=8 * 3600):
        token = secrets.token_urlsafe(40)
        with s.transaction():
            s.db.execute('INSERT INTO sessions(hash,tenant,expires) VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), tenant, time.time() + seconds))
        return token

    app.state.issue_session = issue_session

    @app.middleware('http')
    async def authenticate(request, call_next):
        request.state.request_id = uid()
        if request.url.path.startswith('/api/'):
            bearer = request.headers.get('authorization', '')
            token = bearer[7:] if bearer.startswith('Bearer ') else ''
            digest, tenant = hashlib.sha256(token.encode()).hexdigest(), None
            configured = auth.get(token)
            if isinstance(configured, str) and time.time() < startup + 8 * 3600:
                tenant = configured
            elif isinstance(configured, dict) and configured.get('expires_at', 0) > time.time() and not configured.get('revoked'):
                tenant = configured.get('tenant')
            with s.lock:
                session = s.db.execute('SELECT tenant,expires,revoked FROM sessions WHERE hash=?', (digest,)).fetchone()
                if session and session[1] > time.time() and not session[2]:
                    tenant = session[0]
                key = digest if tenant else (request.client.host if request.client else 'unknown')
                queue, stamp = attempts[key], time.monotonic()
                while queue and queue[0] < stamp - 60:
                    queue.popleft()
                if len(queue) >= rate_limit:
                    response = error(request, 429, 'RATE_LIMITED', 'Too many requests. Try again shortly.', True)
                    response.headers['Retry-After'] = '60'
                    return response
                queue.append(stamp)
                if len(attempts) > 10000:
                    for stale in list(attempts):
                        if attempts[stale] and attempts[stale][-1] < stamp - 60:
                            del attempts[stale]
            if not tenant:
                return error(request, 401, 'UNAUTHENTICATED', 'A valid, unexpired bearer session is required.')
            request.state.tenant, request.state.token_hash = tenant, digest
            origin = request.headers.get('origin')
            if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and origin and origin != f'{request.url.scheme}://{request.url.netloc}' and origin not in cors_origins:
                return error(request, 403, 'ORIGIN_REJECTED', 'Frontend origin is not configured for this deployment.')
            size = request.headers.get('content-length')
            maximum = 25 * 1024 * 1024 if request.url.path.endswith('/bytes') else 65536
            if size:
                try:
                    if int(size) > maximum:
                        return error(request, 413, 'UPLOAD_TOO_LARGE', 'Request exceeds the size limit.')
                except ValueError:
                    return error(request, 400, 'VALIDATION_ERROR', 'Invalid content length.')
            if request.method in {'POST', 'PATCH'}:
                body = bytearray()
                async for block in request.stream():
                    body.extend(block)
                    if len(body) > maximum:
                        return error(request, 413, 'UPLOAD_TOO_LARGE', 'Request exceeds the size limit.')
                # Starlette's cached request replays this bounded body to downstream handlers.
                request._body = bytes(body)
        response = await call_next(request)
        response.headers.update({'X-Request-ID': request.state.request_id, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.exception_handler(APIError)
    async def api_error(request, exc):
        return error(request, exc.status, exc.code, exc.message, exc.retryable)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(request, exc.status_code, 'NOT_FOUND' if exc.status_code == 404 else 'HTTP_ERROR', 'Resource unavailable.' if exc.status_code == 404 else str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        oversized = any(e['loc'] == ('body', 'size_bytes') and e['type'] == 'less_than_equal' for e in exc.errors())
        return error(request, 413 if oversized else 400, 'UPLOAD_TOO_LARGE' if oversized else 'VALIDATION_ERROR', 'Invalid request.', fields=[{'field': '.'.join(map(str, e['loc'][1:])), 'message': e['msg']} for e in exc.errors()])

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        import logging
        logging.getLogger('backend').error('request_id=%s exception_type=%s', request.state.request_id, type(exc).__name__)
        return error(request, 500, 'INTERNAL_ERROR', 'An internal error occurred.', True)

    def idempotent(request, payload, build):
        key = request.headers.get('idempotency-key')
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        tenant, route = request.state.tenant, request.url.path
        if key and len(key) > 200:
            raise APIError(400, 'VALIDATION_ERROR', 'Idempotency key too long.')
        with s.transaction():
            row = s.db.execute('SELECT hash,body FROM idempotency WHERE tenant=? AND route=? AND key=?', (tenant, route, key)).fetchone() if key else None
            if row:
                if row[0] != digest:
                    raise APIError(409, 'IDEMPOTENCY_CONFLICT', 'Key already used for different input.')
                return s.decode(row[1])
            result = build()
            if key:
                s.db.execute('INSERT INTO idempotency VALUES(?,?,?,?,?)', (tenant, route, key, digest, s.encode(result)))
            return result

    def capability(tenant, rid, purpose):
        expires = int(time.time()) + 900
        signature = hmac.new(signing, f'{tenant}|{rid}|{purpose}|{expires}'.encode(), hashlib.sha256).hexdigest()
        return f'{expires}.{signature}', expires

    def check_cap(tenant, rid, purpose, token):
        try:
            exp, signature = token.split('.')
            expected = hmac.new(signing, f'{tenant}|{rid}|{purpose}|{exp}'.encode(), hashlib.sha256).hexdigest()
            if int(exp) < time.time() or not hmac.compare_digest(signature, expected):
                raise ValueError()
        except (ValueError, AttributeError):
            raise APIError(401, 'INVALID_CAPABILITY', 'URL is invalid or expired.')

    def public(doc):
        return {k: v for k, v in doc.items() if k not in {'upload_id', 'uploaded', 'sha256', 'upload_expires'}}

    def source_chunks(tenant, document_id):
        return sorted([c for c in s.all(tenant, 'chunk') if c['document_id'] == str(document_id)], key=lambda c: (c.get('source_part', c.get('page') or 1), c['start_offset']))

    @app.get('/health')
    def health():
        with s.lock:
            s.db.execute('SELECT 1').fetchone()
        return {'status': 'ok', 'version': '1.1.0'}

    @app.post('/demo/session')
    def demo_session(request: Request):
        origin = request.headers.get('origin')
        if not demo or request.url.hostname not in {'127.0.0.1', 'localhost', '::1'} or (request.client and request.client.host not in {'127.0.0.1', '::1', 'testclient'}):
            raise APIError(404, 'NOT_FOUND', 'Resource unavailable.')
        if origin and origin != f'{request.url.scheme}://{request.url.netloc}':
            raise APIError(403, 'ORIGIN_REJECTED', 'Open the local application to start a session.')
        return envelope(request, {'token': issue_session('local-workspace'), 'expires_in': 8 * 3600, 'mode': 'local_demo'})

    @app.get('/api/v1/session')
    def session(request: Request):
        return envelope(request, {'authenticated': True, 'mode': 'local_demo' if demo else 'authenticated', 'retention_days': retention})

    @app.post('/api/v1/session/revoke')
    def revoke(request: Request):
        with s.transaction():
            s.db.execute('UPDATE sessions SET revoked=1 WHERE hash=?', (request.state.token_hash,))
        auth.pop(request.headers.get('authorization', '')[7:], None)
        return envelope(request, {'revoked': True})

    @app.get('/api/v1/documents/capabilities')
    def capabilities(request: Request):
        import shutil
        return envelope(request, {'media_types': sorted(TYPES - ({'application/msword'} if not shutil.which('antiword') else set())), 'max_file_bytes': 25*1024*1024, 'legacy_doc_available': bool(shutil.which('antiword'))})

    @app.get('/api/v1/home')
    def home(request: Request):
        docs = s.all(request.state.tenant, 'document')
        notifications = [{'id': j['id'], 'status': j['status'], 'message': j.get('failure', {}).get('message', 'Completed with warnings') if j.get('failure') else 'Completed with warnings; inspect the source or review.', 'read': s.get(request.state.tenant, 'notification_read', 'read-'+j['id']) is not None} for j in s.all(request.state.tenant, 'job') if j['status'] in {'failed', 'completed_with_warnings'}][-20:]
        return envelope(request, {'notifications': notifications, 'document_counts': {status: sum(d['status'] == status for d in docs) for status in ['uploading', 'processing', 'ready', 'failed']}, 'workflows': [{'id': w, 'available': w in {'review','drafting','research','chat'}, 'name': {'review':'Contract / Case Review','drafting':'Legal Drafting','research':'Legal Research','chat':'RAG Chat'}[w]} for w in ['review', 'drafting', 'research', 'chat']], 'storage_bytes': sum(d['size_bytes'] for d in docs), 'retention_days': retention, 'tenant': {'id': request.state.tenant, 'display_name': request.state.tenant}, 'user': {'display_name': os.getenv('BACKEND_USER_DISPLAY_NAME', 'Local workspace')}, 'recent_activity': sorted(s.all(request.state.tenant, 'audit'), key=lambda a:a['timestamp'], reverse=True)[:10]})

    @app.post('/api/v1/documents/uploads', status_code=201)
    def upload(request: Request, body: Upload):
        if body.content_type not in TYPES:
            raise APIError(400, 'UNSUPPORTED_MEDIA_TYPE', 'Supported formats: PDF, DOC, DOCX, TXT, PNG, JPEG, TIFF.')
        if '/' in body.file_name or '\\' in body.file_name or body.file_name in {'.', '..'} or any(ord(c) < 32 for c in body.file_name):
            raise APIError(400, 'VALIDATION_ERROR', 'File name must be a plain name.')
        def build():
            docs = s.all(request.state.tenant, 'document')
            if len(docs) >= 200 or sum(d['size_bytes'] for d in docs) + body.size_bytes > 500 * 1024 * 1024:
                raise APIError(429, 'STORAGE_QUOTA', 'Workspace limit reached: 200 documents or 500 MB.')
            rid, upload_id = uid(), uid()
            token, exp = capability(request.state.tenant, rid, 'upload')
            doc = {'id': rid, 'name': body.file_name, 'status': 'uploading', 'media_type': body.content_type, 'size_bytes': body.size_bytes, 'sha256': body.sha256.lower(), 'upload_id': upload_id, 'page_count': None, 'ocr_used': False, 'metadata': {}, 'processing': {'stage': 'uploading', 'progress': 0}, 'failure': None, 'warnings': [], 'created_at': now(), 'uploaded': False, 'upload_expires': exp, 'retention_expires_at': time.time() + retention * 86400}
            s.save(request.state.tenant, 'document', doc)
            s.audit(request.state.tenant, 'upload.created', rid, request.state.request_id)
            return {'upload_id': upload_id, 'document_id': rid, 'upload_url': f'/api/v1/documents/{rid}/bytes?token={token}', 'allowed_headers': {'Content-Type': body.content_type, 'Authorization': 'Bearer <token>'}, 'expires_at': datetime.fromtimestamp(exp, timezone.utc).isoformat().replace('+00:00', 'Z')}
        return envelope(request, idempotent(request, body.model_dump(), build))

    @app.put('/api/v1/documents/{document_id}/bytes')
    async def put_bytes(document_id: UUID, request: Request, token: str):
        tenant = request.state.tenant
        doc = get(tenant, 'document', document_id)
        check_cap(tenant, str(document_id), 'upload', token)
        content = bytearray()
        async for block in request.stream():
            content.extend(block)
            if len(content) > doc['size_bytes']:
                raise APIError(413, 'UPLOAD_TOO_LARGE', 'Bytes exceed declared size.')
        if len(content) != doc['size_bytes'] or hashlib.sha256(content).hexdigest() != doc['sha256']:
            raise APIError(422, 'UPLOAD_INTEGRITY_ERROR', 'Size or SHA256 does not match.')
        with s.transaction():
            doc = get(tenant, 'document', document_id)
            if doc['status'] != 'uploading':
                raise APIError(409, 'INVALID_STATE', 'Upload already completed.')
            s.write_blob(str(document_id), bytes(content))
            doc['uploaded'] = True
            s.save(tenant, 'document', doc)
        return envelope(request, {'document_id': str(document_id), 'uploaded': True})

    def queue_document(tenant, doc, request_id):
        if sum(j['status'] not in TERMINAL for j in s.all(tenant, 'job')) >= 20:
            raise APIError(429, 'QUEUE_LIMIT', 'At most 20 documents can be queued at once.', True)
        job = {'id': uid(), 'status': 'queued', 'progress': 0, 'document_id': doc['id'], 'created_at': now(), 'failure': None, 'warnings': []}
        doc.update(status='processing', job_id=job['id'], failure=None, processing={'stage': 'queued', 'progress': 0})
        s.save(tenant, 'document', doc)
        s.save(tenant, 'job', job)
        s.db.execute('INSERT INTO queue VALUES(?,?,?,?)', (job['id'], tenant, doc['id'], 'queued'))
        s.event(job['id'], 'job.progress', status='queued', progress=0, message='Document queued')
        s.audit(tenant, 'document.queued', doc['id'], request_id, job_id=job['id'])
        worker.wake.set()
        return {'document_id': doc['id'], 'job_id': job['id'], 'status': 'queued', 'events_url': f"/api/v1/jobs/{job['id']}/events"}

    @app.post('/api/v1/documents/{document_id}/complete', status_code=202)
    def complete(document_id: UUID, body: Complete, request: Request):
        if len(json.dumps(body.metadata)) > 16000:
            raise APIError(400, 'VALIDATION_ERROR', 'Metadata exceeds 16 KB.')
        def build():
            doc = get(request.state.tenant, 'document', document_id)
            if doc['upload_id'] != str(body.upload_id):
                raise APIError(404, 'NOT_FOUND', 'Upload unavailable.')
            if doc['status'] != 'uploading' or not doc['uploaded']:
                raise APIError(409, 'INVALID_STATE', 'Verified uploaded bytes required; completion is accepted once.')
            if doc['upload_expires'] < time.time():
                raise APIError(409, 'UPLOAD_EXPIRED', 'Upload has expired. Start a new upload.')
            doc['metadata'] = body.metadata
            return queue_document(request.state.tenant, doc, request.state.request_id)
        return envelope(request, idempotent(request, body.model_dump(mode='json'), build))

    @app.post('/api/v1/documents/{document_id}/retry', status_code=202)
    def retry(document_id: UUID, request: Request):
        def build():
            doc = get(request.state.tenant, 'document', document_id)
            if doc['status'] != 'failed' or not doc['uploaded']:
                raise APIError(409, 'INVALID_STATE', 'Only failed or cancelled processing can be retried.')
            return queue_document(request.state.tenant, doc, request.state.request_id)
        return envelope(request, idempotent(request, {}, build))

    @app.get('/api/v1/documents')
    def documents(request: Request, status: str | None = None, query: str = '', cursor: UUID | None = None, limit: int = 25):
        if not 1 <= limit <= 100 or len(query) > 2000 or status not in {None, 'uploading', 'processing', 'ready', 'failed'}:
            raise APIError(400, 'VALIDATION_ERROR', 'Invalid status, query or limit.')
        rows = sorted([d for d in s.all(request.state.tenant, 'document') if (not status or d['status'] == status) and query.casefold() in (d['name'] + ' ' + str(d['metadata'].get('title', ''))).casefold()], key=lambda d: (d['created_at'], d['id']), reverse=True)
        if cursor:
            doc = get(request.state.tenant, 'document', cursor)
            rows = [d for d in rows if (d['created_at'], d['id']) < (doc['created_at'], doc['id'])]
        return envelope(request, {'items': [public(d) for d in rows[:limit]], 'next_cursor': rows[limit - 1]['id'] if len(rows) > limit else None})

    @app.get('/api/v1/documents/{document_id}')
    def document(document_id: UUID, request: Request):
        return envelope(request, public(get(request.state.tenant, 'document', document_id)))

    @app.get('/api/v1/documents/{document_id}/chunks')
    def list_chunks(document_id: UUID, request: Request, cursor: UUID | None = None, limit: int = 25):
        doc = get(request.state.tenant, 'document', document_id)
        if doc['status'] != 'ready':
            raise APIError(409, 'INVALID_STATE', 'Document is not ready.')
        if not 1 <= limit <= 100:
            raise APIError(400, 'VALIDATION_ERROR', 'Limit must be 1Ã¢â‚¬â€œ100.')
        rows = source_chunks(request.state.tenant, document_id)
        if cursor:
            indexes = [i for i, c in enumerate(rows) if c['id'] == str(cursor)]
            if not indexes:
                raise APIError(400, 'INVALID_CURSOR', 'Chunk cursor does not match document.')
            rows = rows[indexes[0] + 1:]
        return envelope(request, {'items': [{k: v for k, v in c.items() if k != 'terms'} for c in rows[:limit]], 'next_cursor': rows[limit - 1]['id'] if len(rows) > limit else None})

    @app.get('/api/v1/documents/{document_id}/chunks/{chunk_id}')
    def chunk(document_id: UUID, chunk_id: UUID, request: Request):
        tenant = request.state.tenant
        get(tenant, 'document', document_id)
        item = get(tenant, 'chunk', chunk_id)
        if item['document_id'] != str(document_id):
            raise APIError(404, 'NOT_FOUND', 'Chunk unavailable.')
        siblings = source_chunks(tenant, document_id)
        pos = next(i for i, c in enumerate(siblings) if c['id'] == str(chunk_id))
        token, _ = capability(tenant, str(document_id), 'preview')
        return envelope(request, {**{k: v for k, v in item.items() if k != 'terms'}, 'previous_text': siblings[pos - 1]['text'] if pos else None, 'next_text': siblings[pos + 1]['text'] if pos + 1 < len(siblings) else None, 'preview_url': f'/api/v1/documents/{document_id}/preview?token={token}'})

    @app.get('/api/v1/documents/{document_id}/preview')
    def preview(document_id: UUID, request: Request, token: str):
        doc = get(request.state.tenant, 'document', document_id)
        check_cap(request.state.tenant, str(document_id), 'preview', token)
        if doc['status'] != 'ready':
            raise APIError(409, 'INVALID_STATE', 'Document is not ready.')
        s.audit(request.state.tenant, 'source.opened', str(document_id), request.state.request_id)
        return Response(s.cipher.decrypt((s.root / f'{document_id}.blob').read_bytes()), media_type=doc['media_type'], headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(doc['name'])})

    @app.post('/api/v1/documents/search')
    def search_documents(body: Search, request: Request):
        tenant, selected = request.state.tenant, set(map(str, body.document_ids))
        for rid in selected:
            if get(tenant, 'document', rid)['status'] != 'ready':
                raise APIError(409, 'DOCUMENT_NOT_READY', 'Search requires ready documents.')
        eligible = {d['id']: d for d in s.all(tenant, 'document') if d['status'] == 'ready' and (not selected or d['id'] in selected) and (not body.jurisdiction or d['metadata'].get('jurisdiction') == body.jurisdiction) and (not body.document_type or d['metadata'].get('document_type') == body.document_type)}
        source = [c for c in s.all(tenant, 'chunk') if c['document_id'] in eligible]
        if len(source) > 4000:
            raise APIError(422, 'SEARCH_SCOPE_TOO_LARGE', 'Select fewer documents for search.')
        hits, results = search(source, body.query, body.limit), []
        for i, hit in enumerate(hits, 1):
            citation = {'id': uid(), 'label': f'S{i}', 'document_id': hit['document_id'], 'document_name': eligible[hit['document_id']]['name'], 'chunk_id': hit['id'], 'page': hit['page'], 'section': hit.get('section'), 'quoted_text': hit['text'], 'start_offset': hit['start_offset'], 'end_offset': hit['end_offset']}
            results.append({'citation': citation, 'score': hit['score'], 'lexical_score': hit['lexical_score'], 'dense_score': hit['dense_score']})
        s.audit(tenant, 'source.search', uid(), request.state.request_id, source_ids=[h['id'] for h in hits], index_version='bm25-lsa-rrf-v1')
        return envelope(request, {'items': results, 'retrieval': {'method': 'BM25 + local dense LSA + reciprocal rank fusion', 'indexed_chunks': len(source), 'model_version': 'bm25-lsa-rrf-v1'}, 'answerability': 'sources_only'})

    @app.delete('/api/v1/documents/{document_id}')
    def delete_document(document_id: UUID, request: Request):
        tenant, rid = request.state.tenant, str(document_id)
        with s.transaction():
            get(tenant, 'document', document_id)
            s.delete_document(tenant, rid)
        (s.root / f'{rid}.blob').unlink(missing_ok=True)
        return envelope(request, {'document_id': rid, 'deleted': True})

    @app.get('/api/v1/jobs/{job_id}')
    def job(job_id: UUID, request: Request):
        return envelope(request, get(request.state.tenant, 'job', job_id))

    @app.post('/api/v1/jobs/{job_id}/cancel')
    def cancel(job_id: UUID, request: Request):
        tenant = request.state.tenant
        with s.transaction():
            job = get(tenant, 'job', job_id)
            if job['status'] not in TERMINAL:
                job['status'] = 'cancelled'
                s.save(tenant, 'job', job)
                if job.get('workflow') in {'review','drafting','research','chat'}:
                    resource_kind = {'review':'review','drafting':'draft','research':'research','chat':'chat_message'}[job['workflow']]
                    report = get(tenant, resource_kind, job['resource_id'])
                    report['status'] = 'cancelled'
                    s.save(tenant, resource_kind, report)
                    s.db.execute('DELETE FROM queue WHERE job=?', (str(job_id),))
                    s.event(str(job_id), 'job.progress', status='cancelled', progress=job['progress'], message='Workflow cancelled')
                    return envelope(request, job)
                doc = get(tenant, 'document', job['document_id'])
                doc.update(status='failed', failure={'code': 'CANCELLED', 'message': 'Processing cancelled.', 'retryable': True}, processing={'stage': 'cancelled', 'progress': job['progress']})
                s.save(tenant, 'document', doc)
                s.db.execute('DELETE FROM queue WHERE job=?', (str(job_id),))
                s.event(str(job_id), 'job.progress', status='cancelled', progress=job['progress'], message='Processing cancelled')
                s.audit(tenant, 'job.cancelled', str(job_id), request.state.request_id)
        return envelope(request, job)

    @app.get('/api/v1/jobs/{job_id}/events')
    async def events(job_id: UUID, request: Request):
        tenant = request.state.tenant
        get(tenant, 'job', job_id)
        try:
            last = int(request.headers.get('last-event-id', '0'))
            if last < 0:
                raise ValueError()
        except ValueError:
            raise APIError(400, 'VALIDATION_ERROR', 'Last-Event-ID must be a nonnegative integer.')
        async def stream():
            nonlocal last
            with s.lock:
                snapshot = get(tenant, 'job', job_id)
                maximum = s.db.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE job=?', (str(job_id),)).fetchone()[0]
            if last > maximum:
                last = maximum
            yield f"event: job.snapshot\ndata: {json.dumps(snapshot)}\n\n"
            heartbeat = time.monotonic()
            while not await request.is_disconnected():
                with s.lock:
                    rows = s.db.execute('SELECT seq,body FROM events WHERE job=? AND seq>? ORDER BY seq', (str(job_id), last)).fetchall()
                for seq, blob in rows:
                    frame = s.decode(blob)
                    yield f"id: {seq}\nevent: {frame['event']}\ndata: {json.dumps(frame['data'])}\n\n"
                    last = seq
                current = s.get(tenant, 'job', job_id)
                if current is None:
                    break
                if current['status'] in TERMINAL:
                    with s.lock:
                        maximum = s.db.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE job=?', (str(job_id),)).fetchone()[0]
                    if last >= maximum:
                        break
                    continue
                if time.monotonic() - heartbeat >= 10:
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': now()})}\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(.2)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})

    from backend.official_sources import install as install_official
    install_official(app,s,worker,envelope,APIError,retention)

    from backend.reviews import install
    install(app, s, worker, get, envelope, APIError, idempotent, review_engine=review_engine, review_llm=review_llm, verify_llm=verify_llm)
    from backend.drafting import install as install_drafting
    install_drafting(app, s, worker, get, envelope, APIError, idempotent, drafting_llm=drafting_llm, verify_llm=verify_llm)
    from backend.research import install as install_research
    install_research(app, s, worker, get, envelope, APIError, idempotent, research_llm=research_llm, verify_llm=verify_llm)

    from backend.chat import install as install_chat
    install_chat(app, s, worker, get, envelope, APIError, idempotent, chat_llm=chat_llm, verify_llm=verify_llm)

    from backend.grounding import install as install_grounding
    install_grounding(app,s,get,envelope,APIError)

    from backend.starter import install as install_starter
    install_starter(app,envelope,APIError)

    @app.get('/')
    def frontend():
        return FileResponse(BASE / 'hacknex2-frontend' / 'index.html')

    @app.get('/backend-preview')
    def backend_preview():
        return FileResponse(BASE / 'frontend' / 'index.html')

    app.mount('/css', StaticFiles(directory=BASE / 'hacknex2-frontend' / 'css', check_dir=False), name='caselens-css')
    app.mount('/js', StaticFiles(directory=BASE / 'hacknex2-frontend' / 'js', check_dir=False), name='caselens-js')
    app.mount('/static', StaticFiles(directory=BASE / 'frontend', check_dir=False), name='static')
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'], allow_headers=['Authorization','Content-Type','Idempotency-Key','Last-Event-ID'], expose_headers=['Content-Disposition','Retry-After'], allow_credentials=False)
    return app


app = create_app()
