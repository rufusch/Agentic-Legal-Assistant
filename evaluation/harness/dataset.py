"""JSONL evaluation datasets: parse referenced documents with the backend parser and map gold quotes to chunks."""
import json
from pathlib import Path

from backend.parsing import chunks as split_chunks, extract

MEDIA = {'.pdf': 'application/pdf', '.txt': 'text/plain', '.md': 'text/plain',
         '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
_CACHE = {}


def _manifest_metadata(path):
    manifest = path.parent / 'manifest.jsonl'
    if manifest.is_file():
        for line in manifest.read_text(encoding='utf-8-sig').splitlines():
            row = json.loads(line) if line.strip() else {}
            if row.get('path') == path.name:
                return row.get('metadata', {})
    return {}


def make_chunks(doc_id, pages, maximum=1200):
    """Chunk records shaped like the production index (page-relative offsets)."""
    rows = []
    for number, text in pages:
        for start, end, value in split_chunks(text, maximum):
            rows.append({'id': f'{doc_id}:p{number}:{start}', 'document_id': doc_id, 'page': number,
                         'source_part': number, 'start_offset': start, 'end_offset': end, 'text': value})
    return rows


def parse_file(path, doc_id=None, metadata=None):
    """Parse PDF/DOCX/TXT with the production parser (plain-text fallback) into a document and its chunks."""
    path = Path(path).resolve()
    key = (str(path), doc_id, json.dumps(metadata or {}, sort_keys=True))
    if key not in _CACHE:
        raw = path.read_bytes()
        media = MEDIA.get(path.suffix.lower(), 'text/plain')
        try:
            pages = [(p['number'], p['text']) for p in extract(raw, media)['pages']]
        except Exception:
            if media != 'text/plain':
                raise
            pages = [(1, raw.decode('utf-8', 'replace'))]
        doc_id = doc_id or path.stem
        meta = {'document_type': 'other', **_manifest_metadata(path), **(metadata or {})}
        document = {'id': doc_id, 'name': path.name, 'metadata': meta, 'pages': pages}
        _CACHE[key] = (document, make_chunks(doc_id, pages))
    return _CACHE[key]


def inline_source(source):
    meta = {'document_type': 'other', **source.get('metadata', {})}
    document = {'id': source['id'], 'name': source.get('name', source['id']), 'metadata': meta, 'pages': [(1, source['text'])]}
    return document, make_chunks(source['id'], document['pages'])


def gold_chunk_ids(documents, chunks, gold):
    """Ids of chunks overlapping each gold quote. A quote absent from its document is a dataset error."""
    by_doc = {d['id']: d for d in documents}
    ids = []
    for g in gold:
        doc = by_doc.get(g['doc'])
        if doc is None:
            raise ValueError(f"Gold reference to unknown document {g['doc']!r}")
        hits = [(n, t.find(g['quote'])) for n, t in doc['pages'] if g['quote'] in t]
        if not hits:
            raise ValueError(f"Gold quote not found verbatim in {g['doc']}: {g['quote'][:60]!r}")
        number, start = hits[0]
        end = start + len(g['quote'])
        ids += [c['id'] for c in chunks if c['document_id'] == doc['id'] and c['page'] == number
                and c['start_offset'] < end and c['end_offset'] > start]
    return list(dict.fromkeys(ids))


def _resolve(root, ref):
    for candidate in (Path(ref), root / ref, Path.cwd() / ref):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(ref)


def load(path, split='all', limit=None):
    """Load JSONL rows into query dicts carrying documents, chunks and gold chunk ids."""
    path = Path(path)
    queries, seen = [], set()
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row['id'] in seen:
            raise ValueError(f'Duplicate query id {row["id"]}')
        seen.add(row['id'])
        if split != 'all' and row.get('split', 'dev') != split:
            continue
        documents, chunks = [], []
        for ref in row.get('documents', []):
            ref = {'path': ref} if isinstance(ref, str) else ref
            doc, rows = parse_file(_resolve(path.parent, ref['path']), ref.get('id'), ref.get('metadata'))
            documents.append(doc); chunks += rows
        for source in row.get('sources', []):
            doc, rows = inline_source(source)
            documents.append(doc); chunks += rows
        if not documents:
            raise ValueError(f'Row {number}: no documents or sources')
        answerable = row.get('answerable', True)
        gold = row.get('gold', [])
        if answerable and not gold:
            raise ValueError(f'Row {number}: answerable queries need gold spans')
        queries.append({'id': row['id'], 'split': row.get('split', 'dev'), 'workflow': row.get('workflow', 'chat'),
                        'question': row['question'], 'answerable': answerable, 'gold': gold,
                        'reference_answer': row.get('reference_answer'), 'documents': documents, 'chunks': chunks,
                        'gold_chunk_ids': gold_chunk_ids(documents, chunks, gold)})
        if limit and len(queries) >= limit:
            break
    return queries
