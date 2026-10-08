"""Single-owner durable SQLite queue with bounded isolated parsing."""
import json
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from backend.parsing import chunks
from backend.retrieval import terms

TERMINAL = {'completed', 'completed_with_warnings', 'failed', 'cancelled'}


def parse_document(raw, media_type, cancelled):
    process = subprocess.Popen([sys.executable, '-m', 'backend.parse_worker', media_type], cwd=Path(__file__).resolve().parent.parent, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    started, first = time.monotonic(), True
    try:
        while True:
            if cancelled():
                return {'cancelled': True}
            if time.monotonic() - started > 90:
                return {'failure': {'code': 'PROCESSING_TIMEOUT', 'message': 'Processing exceeded 90 seconds. Split the document or retry a clearer source.', 'retryable': True}}
            try:
                stdout, _ = process.communicate(input=raw if first else None, timeout=.25)
                if process.returncode != 0:
                    raise ValueError('parser exited')
                return json.loads(stdout)
            except subprocess.TimeoutExpired:
                first = False
    except Exception:
        return {'failure': {'code': 'PARSER_UNAVAILABLE', 'message': 'Document processor unavailable. Retry later.', 'retryable': True}}
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


class Worker:
    def __init__(self, store, retention_days=30):
        self.store = store
        self.retention_days = retention_days
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.parser = parse_document
        self.handlers = {}
        self.handle = self.thread = None

    def cancelled(self, tenant, job):
        state = self.store.get(tenant, 'job', job)
        return self.stop.is_set() or not state or state['status'] == 'cancelled'

    def stage(self, tenant, doc, job, status, progress, message):
        doc['processing'] = {'stage': status, 'progress': progress}
        job.update(status=status, progress=progress)
        self.store.save(tenant, 'document', doc)
        self.store.save(tenant, 'job', job)
        self.store.event(job['id'], 'job.progress', status=status, progress=progress, message=message)

    def process(self, tenant, document_id, job_id):
        s = self.store
        with s.transaction():
            if self.cancelled(tenant, job_id):
                return
            doc, job = s.get(tenant, 'document', document_id), s.get(tenant, 'job', job_id)
            self.stage(tenant, doc, job, 'parsing', .15, 'Reading text and checking scanned pages')
        raw = s.cipher.decrypt((s.root / f'{document_id}.blob').read_bytes())
        duplicate = next((d for d in s.all(tenant, 'document') if d['id'] != document_id and d['status'] == 'ready' and d['sha256'] == doc['sha256'] and d['media_type'] == doc['media_type']), None)
        if duplicate:
            grouped = defaultdict(str)
            for number in range(1, (duplicate.get('page_count') or duplicate['metadata'].get('extracted', {}).get('source_parts', 1)) + 1):
                grouped[number] = ''
            previous = sorted([c for c in s.all(tenant, 'chunk') if c['document_id'] == duplicate['id']], key=lambda c: (c.get('source_part', c.get('page') or 1), c['start_offset']))
            for c in previous:
                grouped[c.get('source_part', c.get('page') or 1)] += c['text']
            result = {'result': {'pages': [{'number': n, 'text': t, 'ocr': duplicate['ocr_used']} for n, t in grouped.items()], 'warnings': [(w['type'], w['severity'], w['title'], w['message']) for w in duplicate.get('warnings', [])], 'parser_version': duplicate.get('parser_version', 'sources-v2')}}
        else:
            result = self.parser(raw, doc['media_type'], lambda: self.cancelled(tenant, job_id))
        if result.get('cancelled') or self.cancelled(tenant, job_id):
            return
        if 'failure' in result:
            self.fail(tenant, doc, job, result['failure'])
            return
        parsed = result['result']
        with s.transaction():
            if self.cancelled(tenant, job_id):
                return
            self.stage(tenant, doc, job, 'indexing', .75, 'Indexing document and source spans')
            for old in s.all(tenant, 'chunk'):
                if old['document_id'] == document_id:
                    s.db.execute('DELETE FROM resources WHERE id=? AND tenant=?', (old['id'], tenant))
            source_ids, first_heading = [], None
            for page in parsed['pages']:
                section = None
                for start, end, text in chunks(page['text']):
                    line = text.strip().split('\n', 1)[0][:120]
                    if line and (line.isupper() or line[:1].isdigit()):
                        section = line
                        first_heading = first_heading or section
                    item = {'id': str(uuid4()), 'document_id': document_id, 'page': page['number'] if doc['media_type'] not in {'application/msword','application/vnd.openxmlformats-officedocument.wordprocessingml.document'} else None, 'source_part': page['number'], 'section': section, 'start_offset': start, 'end_offset': end, 'text': text, 'terms': terms(text)}
                    s.save(tenant, 'chunk', item)
                    source_ids.append(item['id'])
            warnings = [{'id': str(uuid4()), 'type': w[0], 'severity': w[1], 'title': w[2], 'message': w[3], 'resolvable': False} for w in parsed['warnings']]
            metadata = {**doc['metadata']}
            metadata.setdefault('title', Path(doc['name']).stem)
            metadata['extracted'] = {'characters': sum(len(p['text']) for p in parsed['pages']), 'source_parts': len(parsed['pages']), 'first_heading': first_heading}
            status = 'completed_with_warnings' if warnings else 'completed'
            doc.update(status='ready', metadata=metadata, page_count=len(parsed['pages']) if doc['media_type'] not in {'application/msword','application/vnd.openxmlformats-officedocument.wordprocessingml.document'} else None, ocr_used=any(p['ocr'] for p in parsed['pages']), warnings=warnings, chunk_count=len(source_ids), processing={'stage': 'indexed', 'progress': 1}, parser_version=parsed['parser_version'], index_version='bm25-lsa-rrf-v1', failure=None, deduplicated_from=duplicate['id'] if duplicate else None)
            job.update(status=status, progress=1, result_id=document_id, warnings=warnings, failure=None)
            s.save(tenant, 'document', doc)
            s.save(tenant, 'job', job)
            for warning in warnings:
                s.event(job_id, 'warning.created', **warning)
            s.event(job_id, 'job.completed', result_id=document_id, status=status)
            s.db.execute('DELETE FROM queue WHERE job=?', (job_id,))
            s.audit(tenant, 'document.indexed', document_id, source_ids=source_ids, parser_version=parsed['parser_version'], index_version=doc['index_version'])

    def fail(self, tenant, doc, job, failure):
        s = self.store
        with s.transaction():
            if self.cancelled(tenant, job['id']):
                return
            doc.update(status='failed', failure=failure, processing={'stage': 'failed', 'progress': 0})
            job.update(status='failed', failure=failure)
            s.save(tenant, 'document', doc)
            s.save(tenant, 'job', job)
            s.db.execute('DELETE FROM queue WHERE job=?', (job['id'],))
            s.event(job['id'], 'job.failed', **failure)
            s.audit(tenant, 'document.failed', doc['id'], code=failure['code'])

    def cleanup(self):
        s, stamp = self.store, time.time()
        with s.transaction():
            removed = []
            for tenant, blob in s.db.execute("SELECT tenant,body FROM resources WHERE kind='document'").fetchall():
                doc = s.decode(blob)
                expired = doc.get('retention_expires_at', stamp + 1) < stamp
                abandoned = doc['status'] == 'uploading' and doc.get('upload_expires', stamp + 1) + 3600 < stamp
                if expired or abandoned:
                    s.delete_document(tenant, doc['id'])
                    removed.append(doc['id'])
            s.db.execute('DELETE FROM sessions WHERE expires<? OR revoked=1', (stamp,))
        for rid in removed:
            (s.root / f'{rid}.blob').unlink(missing_ok=True)
        with s.lock:
            current = {row[0] for row in s.db.execute("SELECT id FROM resources WHERE kind='document'")}
        for path in s.root.glob('*.blob'):
            if path.stem not in current:
                path.unlink(missing_ok=True)

    def run(self):
        s, cleaned = self.store, 0
        while not self.stop.is_set():
            try:
                if time.monotonic() - cleaned > 60:
                    self.cleanup()
                    cleaned = time.monotonic()
                with s.transaction():
                    row = s.db.execute("SELECT job,tenant,document FROM queue WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
                    if row:
                        s.db.execute("UPDATE queue SET state='running' WHERE job=?", (row[0],))
                if row:
                    try:
                        job = s.get(row[1], 'job', row[0])
                        handler = self.handlers.get(job.get('workflow')) if job else None
                        (handler or self.process)(row[1], row[2], row[0])
                    except Exception:
                        doc, job = s.get(row[1], 'document', row[2]), s.get(row[1], 'job', row[0])
                        if doc and job:
                            self.fail(row[1], doc, job, {'code': 'WORKER_FAILURE', 'message': 'Document processor failed. Retry processing.', 'retryable': True})
                    continue
                self.wake.wait(.25)
                self.wake.clear()
            except Exception:
                self.stop.wait(1)

    def acquire_lock(self):
        self.handle = open(self.store.root / 'worker.lock', 'a+b')
        try:
            self.handle.seek(0)
            if not self.handle.read(1):
                self.handle.write(b'1')
                self.handle.flush()
            self.handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError('Storage already has a worker. Run one application process per storage directory.')

    def start(self):
        self.acquire_lock()
        s = self.store
        with s.transaction():
            for tenant, blob in s.db.execute("SELECT tenant,body FROM resources WHERE kind='job'").fetchall():
                job = s.decode(blob)
                if job['status'] not in TERMINAL:
                    job.update(status='queued', progress=0)
                    s.save(tenant, 'job', job)
                    s.db.execute('INSERT OR REPLACE INTO queue VALUES(?,?,?,?)', (job['id'], tenant, job.get('resource_id', job.get('document_id')), 'queued'))
                    s.event(job['id'], 'job.progress', status='queued', progress=0, message='Resuming queued document processing')
        self.thread = threading.Thread(target=self.run, name='document-worker', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(5)
        if self.handle:
            self.handle.close()
