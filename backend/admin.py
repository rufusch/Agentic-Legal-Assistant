"""Offline session issuance, encrypted backup, restore and key rotation.

Stop the server before maintenance. The same owner lock prevents concurrent workers.
"""
import argparse
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import time
from pathlib import Path

from cryptography.fernet import Fernet

from backend.jobs import Worker
from backend.storage import Store


def backup(store, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    target = sqlite3.connect(destination / 'backend.sqlite3')
    try:
        store.db.backup(target)
    finally:
        target.close()
    for path in store.root.glob('*.blob'):
        shutil.copy2(path, destination / path.name)
    keyfile = store.root / 'local.key'
    if keyfile.exists() and not os.getenv('BACKEND_ENCRYPTION_KEY'):
        shutil.copy2(keyfile, destination / 'local.key')
    (destination / 'backup.json').write_text(json.dumps({'format': 1, 'created_at': time.time(), 'external_key_required': bool(os.getenv('BACKEND_ENCRYPTION_KEY'))}), encoding='utf-8')


def restore(source, destination):
    source, destination = Path(source), Path(destination)
    metadata = json.loads((source / 'backup.json').read_text(encoding='utf-8'))
    if metadata['format'] != 1:
        raise ValueError('Unsupported backup format')
    destination.mkdir(parents=True, exist_ok=False)
    for name in ['backend.sqlite3', 'local.key']:
        if (source / name).exists():
            shutil.copy2(source / name, destination / name)
    for path in source.glob('*.blob'):
        shutil.copy2(path, destination / path.name)
    # Restored copies deliberately have no authenticated sessions.
    db = sqlite3.connect(destination / 'backend.sqlite3')
    db.execute('DELETE FROM sessions')
    db.commit()
    db.close()


def rotate(store, destination):
    """Build a new fully re-encrypted storage directory; never mutate the live source."""
    destination = Path(destination)
    backup(store, destination)
    new_key = Fernet.generate_key()
    cipher = Fernet(new_key)
    db = sqlite3.connect(destination / 'backend.sqlite3')
    try:
        for table, identifiers in [('resources',['id']), ('events',['job','seq']), ('idempotency',['tenant','route','key'])]:
            columns = ','.join(identifiers)
            rows = db.execute(f'SELECT {columns},body FROM {table}').fetchall()
            for *ids, blob in rows:
                encrypted = cipher.encrypt(store.cipher.decrypt(blob))
                where = ' AND '.join(f'{column}=?' for column in identifiers)
                db.execute(f'UPDATE {table} SET body=? WHERE {where}', (encrypted, *ids))
        db.execute('DELETE FROM sessions')
        db.commit()
    finally:
        db.close()
    for path in destination.glob('*.blob'):
        path.write_bytes(cipher.encrypt(store.cipher.decrypt(path.read_bytes())))
    (destination / 'local.key').write_bytes(new_key)
    (destination / 'backup.json').write_text(json.dumps({'format':1,'created_at':time.time(),'external_key_required':False,'rotated':True}), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', default=os.getenv('BACKEND_STORAGE', '.data'))
    commands = parser.add_subparsers(dest='command', required=True)
    issue = commands.add_parser('issue-session')
    issue.add_argument('--tenant', required=True)
    issue.add_argument('--hours', type=float, default=8)
    revoke = commands.add_parser('revoke-session')
    revoke.add_argument('--token-hash', required=True)
    for name in ['backup','rotate-key']:
        commands.add_parser(name).add_argument('--destination', required=True)
    restore_parser = commands.add_parser('restore')
    restore_parser.add_argument('--source', required=True)
    restore_parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    if args.command == 'restore':
        restore(args.source,args.destination)
        return
    store = Store(args.storage, os.getenv('BACKEND_ENCRYPTION_KEY'))
    worker = Worker(store)
    try:
        worker.acquire_lock()
        if args.command == 'issue-session':
            if not 0 < args.hours <= 168:
                raise ValueError('Session lifetime must be greater than zero and at most 168 hours.')
            token = secrets.token_urlsafe(40)
            with store.transaction():
                store.db.execute('INSERT INTO sessions(hash,tenant,expires) VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), args.tenant, time.time()+args.hours*3600))
            print(token)
        elif args.command == 'revoke-session':
            with store.transaction():
                store.db.execute('UPDATE sessions SET revoked=1 WHERE hash=?', (args.token_hash,))
        elif args.command == 'backup':
            backup(store,args.destination)
        elif args.command == 'rotate-key':
            rotate(store,args.destination)
    finally:
        worker.close()
        store.close()


if __name__ == '__main__':
    main()
