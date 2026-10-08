import hashlib
import sys

import pytest
from scripts import download_ranges


def invoke(monkeypatch, out, payload, sha):
    monkeypatch.setattr(sys, 'argv', ['download_ranges', '--url', 'https://example.test/model',
        '--size', str(len(payload)), '--sha256', sha, '--out', str(out), '--workers', '1'])
    return download_ranges.main()


def test_verified_range_is_published(monkeypatch, tmp_path):
    payload = b'known model bytes'
    class Response:
        status = 206
        headers = {'Content-Range': f'bytes 0-{len(payload)-1}/{len(payload)}'}
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, size): return payload
    monkeypatch.setattr(download_ranges.urllib.request, 'urlopen', lambda *a, **k: Response())
    out = tmp_path / 'model.bin'
    invoke(monkeypatch, out, payload, hashlib.sha256(payload).hexdigest())
    assert out.read_bytes() == payload


def test_corrupt_resume_part_is_never_published(monkeypatch, tmp_path):
    payload = b'good'
    out = tmp_path / 'model.bin'
    parts = out.with_suffix('.bin.parts'); parts.mkdir()
    (parts / '00000.part').write_bytes(b'evil')
    with pytest.raises(SystemExit, match='SHA-256 mismatch'):
        invoke(monkeypatch, out, payload, hashlib.sha256(payload).hexdigest())
    assert not out.exists()
