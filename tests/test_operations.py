from cryptography.fernet import Fernet

from backend.admin import backup, restore, rotate
from backend.storage import Store


def test_backup_restore_and_key_rotation(tmp_path):
    original = Store(tmp_path / 'original')
    original.save('tenant-a','document',{'id':'doc','name':'secret contract'})
    original.write_blob('doc',b'private evidence')
    original.event('job','job.progress',status='queued')
    original.db.execute('INSERT INTO sessions(hash,tenant,expires) VALUES(?,?,?)',('hash','tenant-a',9999999999))
    backup(original,tmp_path/'backup')
    restore(tmp_path/'backup',tmp_path/'restored')
    restored = Store(tmp_path/'restored')
    assert restored.get('tenant-a','document','doc')['name'] == 'secret contract'
    assert restored.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
    restored.close()
    rotate(original,tmp_path/'rotated')
    rotated = Store(tmp_path/'rotated')
    assert rotated.get('tenant-a','document','doc')['name'] == 'secret contract'
    assert rotated.cipher.decrypt((rotated.root/'doc.blob').read_bytes()) == b'private evidence'
    assert rotated.decode(rotated.db.execute('SELECT body FROM events').fetchone()[0])['event'] == 'job.progress'
    assert (rotated.root/'local.key').read_bytes() != (original.root/'local.key').read_bytes()
    assert rotated.get('tenant-b','document','doc') is None
    rotated.close()
    original.close()
