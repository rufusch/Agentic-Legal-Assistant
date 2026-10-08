"""Download public legal sources from a URL list into a corpus folder with a hashed manifest.

python -m scripts.fetch_public_corpus corpus/sources.jsonl --out corpus/bail-authorities [--corpus-id bail-authorities]

URL list: JSONL rows {"url": "...", "file": "optional-name.pdf", "metadata": {document_type, title, court, ...}}
or plain lines `URL key=value;key=value` (e.g. `https://... document_type=statute;title=BNSS 2023`). '#' lines are comments.
Writes <out>/<file> plus <out>/manifest.jsonl (schema of corpus/public-starter, loadable by scripts.ingest_corpus).
Re-runs skip files already present with a recorded hash. Only HTTPS. PDFs are checked for the %PDF header;
HTML responses (error/landing pages) are rejected, never saved as sources. Run it on your own machine:
government sites may be unreachable from cloud sandboxes.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, unquote

import httpx

MAX = 25 * 1024 * 1024


def entries(path):
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        if line.startswith('{'):
            yield json.loads(line); continue
        url, _, rest = line.partition(' ')
        yield {'url': url, 'metadata': dict(p.split('=', 1) for p in rest.strip().split(';') if '=' in p)}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('urls'); p.add_argument('--out', required=True); p.add_argument('--corpus-id'); p.add_argument('--jurisdiction', default='IN')
    p.add_argument('--timeout', type=float, default=60); p.add_argument('--insecure-http', action='store_true', help='allow http:// URLs')
    args = p.parse_args(argv)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True); manifest = out / 'manifest.jsonl'
    existing = {r['path']: r for r in map(json.loads, manifest.read_text(encoding='utf-8').splitlines()) if r} if manifest.exists() else {}
    today, ok, failed = date.today().isoformat(), 0, []
    headers = {'User-Agent': 'LexiMind-corpus-fetch/1.0 (research; contact repository maintainers)'}
    with httpx.Client(timeout=args.timeout, follow_redirects=True, headers=headers) as client:
        for item in entries(args.urls):
            url = item['url']
            if urlparse(url).scheme != 'https' and not args.insecure_http: failed.append((url, 'not https')); continue
            name = item.get('file') or re.sub(r'[^A-Za-z0-9._-]+', '-', unquote(Path(urlparse(url).path).name)) or hashlib.sha1(url.encode()).hexdigest()[:12]
            if name in existing and (out / name).exists(): ok += 1; continue
            try:
                r = client.get(url); r.raise_for_status()
                body, ctype = r.content, r.headers.get('content-type', '').split(';')[0].strip().lower()
                if len(body) > MAX: raise ValueError(f'{len(body)} bytes exceeds the 25 MB app limit; split the source')
                if body.lstrip()[:5] == b'%PDF-': name = name if name.lower().endswith('.pdf') else name + '.pdf'
                elif ctype in {'text/html', 'application/xhtml+xml'} or body.lstrip()[:15].lower().startswith((b'<!doctype', b'<html')):
                    raise ValueError('server returned an HTML page, not the document (blocked, moved, or a landing page)')
                elif name.lower().endswith('.pdf'): raise ValueError(f'expected PDF, got {ctype or "unknown type"}')
            except Exception as exc:
                failed.append((url, str(exc)[:200])); print(f'FAIL {url}: {exc}', file=sys.stderr); continue
            (out / name).write_bytes(body)
            meta = {'jurisdiction': args.jurisdiction, 'document_type': 'secondary', **item.get('metadata', {}),
                    'source_url': url, 'corpus_id': args.corpus_id or out.name, 'corpus_version': today, 'retrieved_at': today, 'currency_status': 'not_certified'}
            existing[name] = {'path': name, 'sha256': hashlib.sha256(body).hexdigest(), 'metadata': meta}
            ok += 1; print(f'ok   {name}  {len(body):,} bytes')
    manifest.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in existing.values()), encoding='utf-8')
    print(f'{ok} sources in {manifest}; {len(failed)} failed')
    for url, why in failed: print(f'  - {url}: {why}')
    print('Next: python -m scripts.ingest_dataset', out, '--out datasets/<name>   (or load manifest directly with scripts.ingest_corpus)')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
