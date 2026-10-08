"""Encrypted resources and atomic SQLite transactions for the embedded deployment."""
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet


class Store:
    def __init__(self, root, key=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if not key:
            keyfile = self.root / 'local.key'
            try:
                fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(Fernet.generate_key())
            key = keyfile.read_bytes()
        self.cipher = Fernet(key)
        self.lock = threading.RLock()
        self.depth = 0
        self.db = sqlite3.connect(self.root / 'backend.sqlite3', check_same_thread=False, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=10000')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS resources(id TEXT PRIMARY KEY, tenant TEXT, kind TEXT, body BLOB);
        CREATE INDEX IF NOT EXISTS resource_scope ON resources(tenant,kind);
        CREATE TABLE IF NOT EXISTS idempotency(tenant TEXT, route TEXT, key TEXT, hash TEXT, body BLOB, PRIMARY KEY(tenant,route,key));
        CREATE TABLE IF NOT EXISTS events(job TEXT, seq INTEGER, body BLOB, PRIMARY KEY(job,seq));
        CREATE TABLE IF NOT EXISTS queue(job TEXT PRIMARY KEY, tenant TEXT, document TEXT, state TEXT);
        CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, tenant TEXT, expires REAL, revoked INTEGER DEFAULT 0);
        ''')

    @contextmanager
    def transaction(self):
        with self.lock:
            outer = self.depth == 0
            if outer:
                self.db.execute('BEGIN IMMEDIATE')
            self.depth += 1
            try:
                yield
                if outer:
                    self.db.execute('COMMIT')
            except BaseException:
                if outer:
                    self.db.execute('ROLLBACK')
                raise
            finally:
                self.depth -= 1

    def encode(self, body):
        return self.cipher.encrypt(json.dumps(body, ensure_ascii=False).encode())

    def decode(self, blob):
        return json.loads(self.cipher.decrypt(blob))

    def save(self, tenant, kind, body):
        with self.transaction():
            self.db.execute('INSERT OR REPLACE INTO resources VALUES(?,?,?,?)', (body['id'], tenant, kind, self.encode(body)))

    def get(self, tenant, kind, rid):
        with self.lock:
            row = self.db.execute('SELECT body FROM resources WHERE id=? AND tenant=? AND kind=?', (str(rid), tenant, kind)).fetchone()
        return self.decode(row[0]) if row else None

    def all(self, tenant, kind):
        with self.lock:
            rows = self.db.execute('SELECT body FROM resources WHERE tenant=? AND kind=?', (tenant, kind)).fetchall()
        return [self.decode(row[0]) for row in rows]

    def event(self, job, kind, **data):
        with self.transaction():
            seq = self.db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE job=?', (job,)).fetchone()[0]
            self.db.execute('INSERT INTO events VALUES(?,?,?)', (job, seq, self.encode({'event': kind, 'data': {'job_id': job, **data}})))

    def audit(self, tenant, action, resource_id, request_id=None, **details):
        self.save(tenant, 'audit', {'id': str(uuid4()), 'action': action, 'resource_id': resource_id, 'request_id': request_id, 'timestamp': time.time(), **details})

    def write_blob(self, rid, raw):
        target = self.root / f'{rid}.blob'
        temporary = self.root / f'{rid}.{secrets.token_hex(8)}.tmp'
        try:
            temporary.write_bytes(self.cipher.encrypt(raw))
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def delete_document(self, tenant, rid):
        """Caller must hold a transaction. Files are unlinked after DB commit by caller."""
        related = [r['id'] for r in self.all(tenant, 'chunk') if r['document_id'] == rid]
        related.append('official-'+rid)
        reviews = [r['id'] for r in self.all(tenant, 'review') if rid in r['source_document_ids']]
        versions = self.all(tenant, 'draft_version')
        drafts = {d['id'] for d in self.all(tenant, 'draft') if rid in d['source_document_ids']}
        drafts.update(v['draft_id'] for v in versions if rid in v.get('source_document_ids', []))
        related.extend(drafts)
        for kind in ['draft_version','draft_feedback','draft_training']:
            related.extend(v['id'] for v in self.all(tenant,kind) if v['draft_id'] in drafts)
        research = {r['id'] for r in self.all(tenant,'research') if rid in r['source_document_ids']}
        related.extend(research)
        for kind in ['research_feedback','research_training']:
            related.extend(r['id'] for r in self.all(tenant,kind) if r['research_id'] in research)
        conversations = {c['id'] for c in self.all(tenant,'conversation') if rid in c.get('source_document_ids',[])}
        chat_messages = {m['id'] for m in self.all(tenant,'chat_message') if m['conversation_id'] in conversations or rid in m.get('source_document_ids',[])}
        related.extend(conversations); related.extend(chat_messages)
        for kind in ['chat_feedback','chat_training']:
            related.extend(r['id'] for r in self.all(tenant,kind) if r['message_id'] in chat_messages)
        related.extend(reviews)
        related.extend(f['id'] for f in self.all(tenant, 'feedback') if rid in f.get('source_document_ids', []))
        jobs = [j['id'] for j in self.all(tenant, 'job') if j.get('document_id') == rid or j.get('resource_id') in set(reviews) | drafts | research | chat_messages]
        for job in jobs:
            self.db.execute('DELETE FROM resources WHERE id=? AND tenant=?', ('read-'+job, tenant))
            self.db.execute('DELETE FROM events WHERE job=?', (job,))
            self.db.execute('DELETE FROM queue WHERE job=?', (job,))
        for resource in [rid, *related, *jobs]:
            self.db.execute('DELETE FROM resources WHERE id=? AND tenant=?', (resource, tenant))
        for audit in self.all(tenant, 'audit'):
            if audit['resource_id'] in {rid, *related, *jobs} or set(audit.get('source_ids', [])) & set(related):
                self.db.execute('DELETE FROM resources WHERE id=? AND tenant=?', (audit['id'], tenant))
        # Responses may include document/job identifiers; removing them prevents stale replay.
        for route, key, body in self.db.execute('SELECT route,key,body FROM idempotency WHERE tenant=?', (tenant,)).fetchall():
            response = self.decode(body)
            if response.get('document_id') == rid or response.get('job_id') in jobs or response.get('data', {}).get('review_id') in reviews or response.get('data', {}).get('draft_id') in drafts or response.get('data', {}).get('research_id') in research or response.get('data', {}).get('conversation_id') in conversations:
                self.db.execute('DELETE FROM idempotency WHERE tenant=? AND route=? AND key=?', (tenant, route, key))

    def close(self):
        self.db.close()
