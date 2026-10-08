"""Normalize an unknown legal dataset into a LexiMind bundle: corpus manifest, eval set and grounded SFT data.

python -m scripts.ingest_dataset <path> --out datasets/<name> [--heldout-frac 0.3] [--map question=colA,answer=colB]
       [--metadata-defaults jurisdiction=IN,document_type=judgment] [--dry-run] [--limit N]

<path> may be a folder (PDF/DOCX/DOC/TXT/MD/HTML documents and/or JSON/JSONL/CSV/TSV/Parquet/Arrow tables),
a single file, or a HuggingFace hub id (needs `datasets`). Output bundle:
  documents/     copied originals (HTML/MD/non-UTF8 text converted to UTF-8 .txt, because the app accepts .txt)
  manifest.jsonl corpus rows {path, sha256, metadata} accepted by scripts/ingest_corpus.py
  eval.jsonl     {id, split: dev|heldout, workflow, question, documents, gold:[{doc, quote, page}], answerable, reference_answer?}
  sft.jsonl      {"messages":[system,user,assistant], "meta":{...}} in backend.chat's grounded proposition format (dev rows only)
  report.json    counts, column mappings, gold-match levels, rejects; *_flagged/_rejected.jsonl hold dropped rows.
Gold quotes are verified against text parsed with backend.parsing (the app's own parser) and stored as the exact
substring. Held-out rows are never written to sft.jsonl. Nothing here invents facts: metadata is inferred only from
text patterns and is marked `metadata_inferred`.
"""
import argparse
import csv
import hashlib
import io
import json
import mimetypes
import re
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from backend import parsing  # noqa: E402
from backend.chat import SYSTEM, Answer  # noqa: E402
from backend.drafting_engine import source_packet  # noqa: E402
from backend.grounding import material_values_supported  # noqa: E402
from backend.retrieval import search, terms  # noqa: E402

DOC_EXT = {'.pdf': 'application/pdf', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
           '.doc': 'application/msword', '.txt': 'text/plain', '.text': 'text/plain', '.md': 'text/plain',
           '.html': 'text/html', '.htm': 'text/html', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.tif': 'image/tiff', '.tiff': 'image/tiff'}
TABLE_EXT = {'.json', '.jsonl', '.ndjson', '.csv', '.tsv', '.parquet', '.arrow'}
SKIP_NAMES = {'manifest.jsonl', 'report.json', 'eval.jsonl', 'sft.jsonl', 'eval_flagged.jsonl', 'sft_rejected.jsonl'}
DOC_TYPES = {'statute', 'judgment', 'case', 'contract', 'secondary', 'past_draft', 'user_input'}
PACKET_CHARS = 18000  # same bound as backend/chat.py

SYN = {  # field -> synonyms (normalized column names); earlier fields claim columns first
    'question': ['question', 'query', 'q', 'prompt', 'instruction', 'user_query', 'question_text', 'input'],
    'answer': ['answer', 'answers', 'reference_answer', 'gold_answer', 'expected_answer', 'ground_truth', 'response', 'output', 'a', 'target', 'completion'],
    'quote': ['quote', 'gold_quote', 'evidence_quote', 'supporting_text', 'supporting_facts', 'gold_passage', 'rationale', 'answer_span', 'span', 'citation_text', 'evidence'],
    'context': ['context', 'passage', 'passages', 'contexts', 'text', 'document_text', 'paragraph', 'content', 'chunk', 'body', 'judgment_text', 'full_text', 'source_text', 'evidence_text'],
    'gold': ['gold', 'gold_sources'],
    'doc': ['documents', 'doc', 'document', 'file', 'filename', 'file_name', 'path', 'doc_path', 'document_path', 'source_file', 'doc_id', 'document_id', 'doc_ids', 'case_id'],
    'id': ['id', 'qid', 'question_id', 'uid', '_id', 'example_id', 'idx', 'key'],
    'title': ['title', 'case_name', 'doc_title', 'case_title', 'name'],
    'citation': ['neutral_citation', 'citation', 'case_citation', 'cite', 'reference'],
    'source_url': ['source_url', 'url', 'link', 'source'],
    'court': ['court', 'court_name', 'bench'],
    'decided_at': ['decided_at', 'judgment_date', 'decision_date', 'date_of_judgment', 'date'],
    'document_type': ['document_type', 'doc_type', 'type', 'category'],
    'jurisdiction': ['jurisdiction', 'country'],
    'split': ['split', 'subset', 'partition'],
    'workflow': ['workflow', 'task', 'task_type'],
    'answerable': ['answerable', 'is_answerable', 'has_answer'],
    'unanswerable': ['is_impossible', 'unanswerable', 'no_answer'],
    'kind': ['kind', 'proposition_kind'],
    'answer_start': ['answer_start'],
}
FUZZY = {'question', 'answer', 'context', 'title'}  # allow substring column matches for these only

CITATION_RES = [r'\b(?:19|20)\d\d\s+INSC\s+\d+\b', r'\(\s*(?:19|20)\d\d\s*\)\s*\d+\s+SCC\s+\d+', r'\b(?:19|20)\d\d\s*:\s*[A-Z]{2,6}\s*:\s*\d+(?:-[A-Z]+)?\b',
                r'\bAIR\s+(?:19|20)\d\d\s+SC\s+\d+\b', r'\b(?:19|20)\d\d\s+SCC\s+OnLine\s+\w+\s+\d+\b']
MONTHS = 'january|february|march|april|may|june|july|august|september|october|november|december'
MON = {m[:3]: i for i, m in enumerate(MONTHS.split('|'), 1)}
LEGAL_RE = re.compile(r'\b(section|sections|article|act|code|sanhita|held|holds|law|principle|statute|provision|fundamental right|punishable|entitled|mandatory|settled)\b', re.I)


def norm_col(name): return re.sub(r'[^a-z0-9]+', '_', str(name).strip().lower()).strip('_')
def sha(text): return hashlib.sha256(text.encode('utf-8')).hexdigest()
def qnorm(text): return ' '.join(re.findall(r'\w+', str(text).casefold()))
def kv(text): return dict(p.split('=', 1) for p in (text or '').split(',') if '=' in p)


# ---------------------------------------------------------------- text location (verified gold spans)
TRANS = {'‘': "'", '’': "'", '“': '"', '”': '"', '–': '-', '—': '-', ' ': ' ', '­': ''}


def _normalize(text, drop_space):
    out, index = [], []
    for i, ch in enumerate(text):
        ch = TRANS.get(ch, ch)
        if not ch: continue
        if ch.isspace():
            if drop_space or (out and out[-1] == ' ') or not out: continue
            ch = ' '
        low = ch.lower()
        out.append(low if len(low) == 1 else ch); index.append(i)
    return ''.join(out), index


def locate(quote, pages):
    """Return (page, start, end, exact_substring, level) or None. Levels: exact < normalized < nospace."""
    quote = (quote or '').strip()
    if len(quote) < 3: return None
    for number, text in pages:
        k = text.find(quote)
        if k >= 0: return number, k, k + len(quote), quote, 'exact'
    for level, drop in (('normalized', False), ('nospace', True)):
        if drop and len(quote) < 20: break
        q, _ = _normalize(quote, drop); q = q.strip()
        for number, text in pages:
            t, index = _normalize(text, drop)
            k = t.find(q)
            if k >= 0 and q:
                start, end = index[k], index[k + len(q) - 1] + 1
                return number, start, end, text[start:end], level
    return None


def sentence_around(text, start, end):
    left = max(text.rfind('. ', 0, start), text.rfind('\n\n', 0, start), text.rfind('.\n', 0, start))
    left = 0 if left < 0 else left + 2
    m = re.search(r'[.!?](?=\s|$)|\n\n', text[max(end - 1, start):])
    right = max(end - 1, start) + m.end() if m else len(text)
    return left + (len(text[left:right]) - len(text[left:right].lstrip())), left + len(text[left:right].rstrip())


def overlap(answer, quote):
    a = set(terms(answer)); return len(a & set(terms(quote))) / len(a) if a else 0.0


# ---------------------------------------------------------------- metadata inference
def parse_date(text):
    cands = []
    for m in re.finditer(r'\b(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)\d\d)\b', text): cands.append((m.start(), int(m[3]), int(m[2]), int(m[1])))
    for m in re.finditer(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTHS}|[a-z]{{3}})\.?,?\s+((?:19|20)\d\d)\b', text, re.I):
        if m[2][:3].lower() in MON: cands.append((m.start(), int(m[3]), MON[m[2][:3].lower()], int(m[1])))
    for m in re.finditer(rf'\b({MONTHS}|[a-z]{{3}})\.?\s+(\d{{1,2}}),?\s+((?:19|20)\d\d)\b', text, re.I):
        if m[1][:3].lower() in MON: cands.append((m.start(), int(m[3]), MON[m[1][:3].lower()], int(m[2])))
    good = []
    for pos, y, mo, d in sorted(cands):
        try: good.append(date(y, mo, d).isoformat())
        except ValueError: pass
    return good


def infer_metadata(text, filename):
    head, tail = text[:6000], text[-3000:]
    meta, low = {}, head.lower()
    statute = sum(bool(re.search(p, head, re.I)) for p in [r'\bACT,?\s*(?:NO\.?\s*\d+\s*OF\s*)?(?:18|19|20)\d\d\b', r'\bsanhita\b', r'be it enacted', r'arrangement of sections', r'short title', r'\bCODE OF\b', r'\bconstitution of india\b', r'\bordinance\b', r'\brules,\s*(?:19|20)\d\d'])
    judgment = sum(bool(re.search(p, head, re.I)) for p in [r'\bjudgment\b', r'\bpetitioner', r'\brespondent', r'\bappellant', r'\b(?:versus|vs\.?)\b', r'in the (?:supreme|high) court', r'\breportable\b', r'\bcoram\b', r'\bbail application\b', r'\b[A-Z]+\s*,\s*J\.', r'\bcriminal appeal\b', r'\bwrit petition\b'])
    contract = sum(bool(re.search(p, head, re.I)) for p in [r'\bagreement\b', r'\bhereinafter (?:referred|called)', r'\bwhereas\b', r'\bin witness whereof', r'\bparty of the first part', r'\bterms and conditions'])
    scores = {'statute': statute * 1.2, 'judgment': judgment, 'contract': contract}
    best = max(scores, key=scores.get)
    if scores[best] >= 2: meta['document_type'] = best
    m = re.search(r'IN THE (SUPREME COURT OF INDIA|HIGH COURT OF [A-Z][A-Z .&]+?|[A-Z][A-Z .]+? HIGH COURT)\b(?:\s+AT\s+[A-Z]+)?', head, re.I)
    if m: meta['court'] = ' '.join(m[1].split()).title().replace(' Of ', ' of ')
    elif re.search(r'supreme court of india', low): meta['court'] = 'Supreme Court of India'
    for pattern in CITATION_RES:
        c = re.search(pattern, head)
        if c: meta['neutral_citation' if re.search(r'INSC|:', c[0]) else 'citation'] = ' '.join(c[0].split()); break
    if meta.get('document_type') == 'judgment':
        lab = re.search(r'(?:date of (?:decision|judgment|judgement|order|pronouncement)|decided on|pronounced on)\s*[:\-]?\s*(.{0,40})', text, re.I)
        dates = parse_date(lab[1]) if lab else []
        dates = dates or parse_date(tail)[-1:] or parse_date(head)[:1]
        if dates: meta['decided_at'] = dates[0]
        role = r'\s*(?:\.{2,}|…+)?\s*(?:appellant|respondent|petitioner|applicant|accused|complainant|opposite part(?:y|ies))s?(?:\(s\))?\s*$'
        cause = head[:2500]
        lines = [l.strip() for l in cause.splitlines() if l.strip()]
        k = next((i for i, l in enumerate(lines) if re.fullmatch(r'(?i)v(?:s\.?|ersus|\.)', l)), None)
        if k and k + 1 < len(lines):
            a, b = (re.sub(role, '', x, flags=re.I).strip() for x in (lines[k - 1], lines[k + 1]))
            if a and b: meta['title'] = ' '.join(f'{a} v. {b}'.split())
        if 'title' not in meta:
            parties = re.search(r'^[ \t]*(\S.{2,120}?)[ \t]+(?:v\.|vs\.?|versus)[ \t]+(.{3,120}?)[ \t]*$', cause, re.I | re.M)
            if parties: meta['title'] = ' '.join(f'{parties[1]} v. {parties[2]}'.split())
    if meta.get('document_type') == 'statute':
        t = re.search(r'\b(THE\s+)?([A-Z][A-Za-z() ]{3,90}?(?:ACT|SANHITA|CODE|ADHINIYAM)),?\s*((?:18|19|20)\d\d)\b', head)
        if t: meta['title'] = ' '.join(f'{t[2]}, {t[3]}'.split()).title().replace(' Of ', ' of ')
    if 'title' not in meta:
        line = next((l.strip() for l in head.splitlines() if 8 <= len(l.strip()) <= 140 and re.search(r'[A-Za-z]{3}', l)), None)
        meta['title'] = line or Path(filename).stem
    return meta


# ---------------------------------------------------------------- readers
def read_text(raw):
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try: return raw.decode(enc), enc
        except UnicodeDecodeError: pass


def html_text(raw):
    text, _ = read_text(raw)
    try:
        import lxml.html
        tree = lxml.html.fromstring(text)
        for bad in tree.xpath('//script|//style|//noscript'): bad.drop_tree()
        for br in tree.xpath('//br|//p|//div|//li|//tr|//h1|//h2|//h3|//h4'): br.tail = '\n' + (br.tail or '')
        text = tree.text_content()
    except Exception:
        text = re.sub(r'<[^>]+>', ' ', re.sub(r'(?is)<(script|style).*?</\1>', '', text))
    return re.sub(r'\n\s*\n+', '\n\n', re.sub(r'[ \t]+', ' ', text)).strip()


def read_table(path):
    ext = path.suffix.lower()
    if ext in {'.jsonl', '.ndjson'}:
        with path.open(encoding='utf-8-sig') as f: return [json.loads(l) for l in f if l.strip()]
    if ext in {'.csv', '.tsv'}:
        raw = path.read_bytes(); text, _ = read_text(raw)
        dialect = 'excel-tab' if ext == '.tsv' else csv.Sniffer().sniff(text[:20000], delimiters=',;\t|') if text.strip() else 'excel'
        csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
        return list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if ext in {'.parquet', '.arrow'}:
        try:
            import pyarrow as pa, pyarrow.parquet as pq
        except ImportError: raise SystemExit(f'{path}: install pyarrow to read {ext} files (pip install pyarrow)')
        if ext == '.parquet': return pq.read_table(path).to_pylist()
        try: return pa.ipc.open_stream(str(path)).read_all().to_pylist()
        except Exception: return pa.ipc.open_file(str(path)).read_all().to_pylist()
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if isinstance(data, dict) and isinstance(data.get('data'), list) and data['data'] and isinstance(data['data'][0], dict) and 'paragraphs' in data['data'][0]:
        rows = []  # SQuAD layout
        for art in data['data']:
            for para in art['paragraphs']:
                for qa in para.get('qas', []): rows.append({**qa, 'context': para['context'], 'title': art.get('title')})
        return rows
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        data = max(lists, key=len) if lists else [data]
    return [r for r in data if isinstance(r, dict)]


def mapping(columns, override):
    normalized = {norm_col(c): c for c in columns}; used, result = set(), {}
    for field, col in override.items(): result[field] = col; used.add(col)
    for field, names in SYN.items():
        if field in result: continue
        hit = next((normalized[n] for n in names if n in normalized and normalized[n] not in used), None)
        if hit is None and field in FUZZY:
            hit = next((orig for n, orig in normalized.items() if orig not in used and any(s in n.split('_') for s in names[:3])), None)
        if hit is not None: result[field] = hit; used.add(hit)
    return result


def get(row, col):
    value = row
    for part in str(col).split('.') if col not in row else [col]:
        value = value.get(part) if isinstance(value, dict) else None
    return value


def first_text(value):
    if isinstance(value, dict):
        for k in ('text', 'answer', 'value', 'quote'):
            if k in value: return first_text(value[k])
        return None
    if isinstance(value, (list, tuple)): return next((t for t in map(first_text, value) if t), None)
    if value is None: return None
    if isinstance(value, float) and value != value: return None
    s = str(value).strip()
    return s or None


def contexts(value):
    """Context may be text, a list of passages, HotpotQA [title, [sentences]] pairs or dicts."""
    if value is None: return []
    if isinstance(value, str):
        if value.strip().startswith('['):
            try: return contexts(json.loads(value))
            except ValueError: pass
        return [(None, value)] if value.strip() else []
    if isinstance(value, dict):
        if isinstance(value.get('title'), list) and isinstance(value.get('sentences'), list):
            return [(t, ''.join(s)) for t, s in zip(value['title'], value['sentences'])]
        return [(value.get('title'), first_text(value.get('text') or value.get('content') or value.get('passage')) or '')]
    out = []
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[1], list): out.append((item[0], ''.join(map(str, item[1]))))
        else: out += contexts(item)
    return [(t, x) for t, x in out if x and x.strip()]


def truthy(value):
    if isinstance(value, bool): return value
    if value is None or value == '': return None
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 't'}


# ---------------------------------------------------------------- bundle
class Bundle:
    def __init__(self, out, args):
        self.out, self.args = out, args
        self.defaults = {'jurisdiction': 'IN', **kv(args.metadata_defaults)}
        self.docs, self.alias, self.report = {}, {}, Counter()
        self.failures, self.limits = [], []
        self.corpus_id = args.corpus_id or out.name

    def _name(self, rel_hint, suffix):
        base = re.sub(r'[^A-Za-z0-9._-]+', '-', str(Path(rel_hint).with_suffix('') if Path(rel_hint).suffix.lower() in DOC_EXT else rel_hint).replace('\\', '/').replace('/', '__')).strip('-')[:120] or 'doc'
        name, n = f'{base}{suffix}', 1
        while f'documents/{name}' in self.docs: n += 1; name = f'{base}-{n}{suffix}'
        return f'documents/{name}'

    def _register(self, rel, raw, pages, meta, aliases):
        text = '\n'.join(t for _, t in pages)
        inferred = infer_metadata(text, Path(rel).name)
        final = {**self.defaults, **{k: v for k, v in inferred.items() if k not in meta}, **meta}
        if inferred.get('document_type') and 'document_type' not in meta: final['document_type'] = inferred['document_type']
        final['document_type'] = final.get('document_type') if final.get('document_type') in DOC_TYPES else 'secondary'
        final.update(corpus_id=self.corpus_id, corpus_version=self.args.corpus_version, metadata_inferred=sorted(k for k in inferred if k not in meta))
        final.setdefault('retrieved_at', date.today().isoformat()); final.setdefault('currency_status', 'not_certified')
        final = {k: v for k, v in final.items() if v not in (None, '', [])}
        self.docs[rel] = {'path': rel, 'sha256': hashlib.sha256(raw).hexdigest(), 'metadata': final, 'pages': pages, 'size': len(raw)}
        if len(pages) > parsing.MAX_PAGES or len(raw) > 25 * 1024 * 1024: self.limits.append(rel)
        for a in [rel, *aliases]:
            if a: self.alias.setdefault(str(a).strip().replace('\\', '/').lower(), rel)
        self.report['documents_' + final['document_type']] += 1
        if not self.args.dry_run:
            dest = self.out / rel; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(raw)
        return rel

    def add_file(self, src, rel_hint, meta=None):
        ext = src.suffix.lower(); raw = src.read_bytes(); media = DOC_EXT[ext]; converted = None
        try:
            if media == 'text/html': converted = html_text(raw).encode('utf-8')
            elif media == 'text/plain':
                text, enc = read_text(raw)
                if ext != '.txt' or enc != 'utf-8-sig' or raw.startswith(b'\xef\xbb\xbf'): converted = text.encode('utf-8')
            data = converted if converted is not None else raw
            parsed = parsing.extract(data, 'text/plain' if converted is not None else media)
        except parsing.ParseFailure as exc:
            self.failures.append({'file': str(rel_hint), 'code': exc.code, 'message': exc.message}); return None
        except Exception as exc:
            self.failures.append({'file': str(rel_hint), 'code': type(exc).__name__, 'message': str(exc)[:300]}); return None
        pages = [(p['number'], p['text']) for p in parsed['pages']]
        meta = dict(meta or {})
        if converted is not None: meta['converted_from'] = Path(rel_hint).name; self.report['documents_converted_to_txt'] += 1
        rel = self._register(self._name(rel_hint, '.txt' if converted is not None else ext), data, pages, meta,
                             [str(rel_hint), Path(rel_hint).name, Path(rel_hint).stem, meta.get('doc_id')])
        return rel

    def add_text(self, text, title, meta, aliases=()):
        key = sha(text)
        if key in self.alias: return self.alias[key]
        meta = {k: v for k, v in {**meta, 'title': title or meta.get('title')}.items() if v}
        rel = self._register(self._name(f'{(title or "passage")[:60]}-{key[:8]}', '.txt'), text.encode('utf-8'), [(1, text)], meta, [key, *aliases])
        return rel

    def resolve(self, ref):
        if ref is None: return None
        ref = str(ref).strip().replace('\\', '/').lower()
        return self.alias.get(ref) or self.alias.get(Path(ref).name) or self.alias.get(Path(ref).stem) or (ref if ref in self.docs else None)


def doc_meta(row, cols):
    meta = {}
    for field, key in [('title', 'title'), ('court', 'court'), ('decided_at', 'decided_at'), ('source_url', 'source_url'), ('jurisdiction', 'jurisdiction'), ('document_type', 'document_type')]:
        v = first_text(get(row, cols[field])) if field in cols else None
        if v: meta[key] = v
    c = first_text(get(row, cols['citation'])) if 'citation' in cols else None
    if c: meta['neutral_citation' if re.search(r'INSC|:', c) else 'citation'] = c
    if meta.get('decided_at'):
        raw = meta.pop('decided_at')
        d = [raw[:10]] if re.match(r'(?:19|20)\d\d-\d\d-\d\d', raw) else parse_date(raw)
        if d: meta['decided_at'] = d[0]
    if meta.get('document_type'):
        t = meta['document_type'].strip().lower()
        meta['document_type'] = {'act': 'statute', 'law': 'statute', 'statutes': 'statute', 'case': 'judgment', 'judgement': 'judgment', 'order': 'judgment', 'agreement': 'contract'}.get(t, t)
        if meta['document_type'] not in DOC_TYPES: meta['metadata_document_type_raw'] = meta.pop('document_type')
    return meta


# ---------------------------------------------------------------- QA processing
def build_gold(bundle, row, cols, rels, answer, answer_start):
    """Explicit gold > short context > sentence containing the answer > best-overlap sentence."""
    golds, source = [], None
    explicit = get(row, cols['gold']) if 'gold' in cols else None
    if isinstance(explicit, str):
        try: explicit = json.loads(explicit)
        except ValueError: explicit = None
    if isinstance(explicit, list) and explicit and isinstance(explicit[0], dict):
        for g in explicit:
            rel = bundle.resolve(g.get('doc') or g.get('document')) or (rels[0] if len(rels) == 1 else None)
            golds.append((rel, first_text(g.get('quote') or g.get('text')))); source = 'explicit'
    elif 'quote' in cols and first_text(get(row, cols['quote'])):
        value = get(row, cols['quote']); quotes = value if isinstance(value, list) else [value]
        golds = [(None, first_text(q)) for q in quotes if first_text(q)]; source = 'explicit'
    if golds: return golds, source
    ctx_docs = [r for r in rels if bundle.docs[r]['metadata'].get('from_context')]
    if len(ctx_docs) == 1 and len(bundle.docs[ctx_docs[0]]['pages'][0][1]) <= 1500:
        return [(ctx_docs[0], bundle.docs[ctx_docs[0]]['pages'][0][1].strip())], 'context'
    if not answer: return [], None
    for rel in rels:
        pages = bundle.docs[rel]['pages']
        if answer_start is not None and len(pages) == 1 and pages[0][1][answer_start:answer_start + len(answer)] == answer:
            hit = (1, answer_start, answer_start + len(answer))
        else:
            hit = locate(answer, pages) if len(answer) >= 3 else None
        if hit:
            text = dict(pages)[hit[0]]; s, e = sentence_around(text, hit[1], hit[2])
            return [(rel, text[s:e])], 'answer_sentence'
    best = (0, None, None)
    for rel in rels:
        for _, text in bundle.docs[rel]['pages']:
            for m in re.finditer(r'[^.\n]+(?:[.\n]|$)', text):
                score = overlap(answer, m[0])
                if score > best[0] and len(m[0].strip()) > 20: best = (score, rel, m[0].strip())
    if best[0] >= 0.6: return [(best[1], best[2])], 'answer_overlap'
    return [], None


def chunk_rows(bundle, rel):
    out = []
    for number, text in bundle.docs[rel]['pages']:
        for start, end, value in parsing.chunks(text):
            out.append({'id': f'{rel}#{number}:{start}', 'document_id': rel, 'source_part': number, 'page': number, 'start_offset': start, 'end_offset': end, 'text': value})
    return out


def sft_example(bundle, item, spans, args):
    """Build a backend.chat-format example; return (example, None) or (None, reason)."""
    rels = item['documents']
    if not rels: return None, 'no_documents'
    all_chunks = [c for r in rels for c in chunk_rows(bundle, r)]
    forced = [c for c in all_chunks for (r, p, s, e) in spans if c['document_id'] == r and c['page'] == p and c['start_offset'] < e and c['end_offset'] > s]
    chosen, size, seen = [], 0, set()
    for c in forced + search(all_chunks, item['question'], 10):
        if c['id'] in seen or size + len(c['text']) > PACKET_CHARS: continue
        chosen.append(c); seen.add(c['id']); size += len(c['text'])
    if len({c['id'] for c in forced} - seen): return None, 'gold_exceeds_context_budget'
    documents = [{'id': r, 'name': Path(r).name, 'metadata': bundle.docs[r]['metadata']} for r in rels]
    catalog, packet = source_packet(documents, chosen)
    propositions = []
    if item['answerable']:
        refs = [k for k, v in catalog.items() for (r, p, s, e) in spans
                if v['chunk']['document_id'] == r and v['chunk']['page'] == p and v['chunk']['start_offset'] + v['offset'] < e and v['chunk']['start_offset'] + v['offset'] + len(v['quote']) > s]
        refs = list(dict.fromkeys(refs))[:8]
        if not refs: return None, 'gold_not_in_packet'
        answer = item.get('reference_answer') or ''
        text = answer if len(answer.split()) >= 4 else ' '.join(g['quote'].split())
        if len(text) > 1800: return None, 'answer_too_long'
        quotes = [catalog[r]['quote'] for r in refs]
        if not material_values_supported(text, quotes): return None, 'numbers_not_in_passage'
        score = overlap(text, '\n'.join(quotes))
        if score < args.min_overlap: return None, f'low_lexical_overlap'
        types = {bundle.docs[catalog[r]['chunk']['document_id']]['metadata'].get('document_type') for r in refs}
        kind = item.get('kind') or ('legal' if 'statute' in types or ('judgment' in types and LEGAL_RE.search(text)) else 'fact')
        propositions = [{'text': text, 'kind': kind, 'source_ids': refs}]
    answer = Answer.model_validate({'propositions': propositions})
    context = {'question': item['question'], 'history': [], 'sources': packet}
    return {'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)},
                         {'role': 'assistant', 'content': json.dumps(answer.model_dump(), ensure_ascii=False)}],
            'meta': {'eval_id': item['id'], 'documents': rels, 'abstain': not propositions, 'workflow': 'chat'}}, None


def split_of(explicit, key, frac):
    if explicit:
        e = str(explicit).lower()
        if any(w in e for w in ('test', 'heldout', 'held_out', 'hidden', 'eval')): return 'heldout'
        if any(w in e for w in ('train', 'dev', 'valid')): return 'dev'
    return 'heldout' if int(sha(key)[:8], 16) / 2**32 < frac else 'dev'


def collect(source, args):
    """Return (document files, table files, hub rows)."""
    if not source.exists():
        if re.fullmatch(r'[\w.-]+/[\w.-]+', str(source)):
            from datasets import load_dataset
            ds = load_dataset(str(source)); return [], [], [(r, name) for name in ds for r in ds[name]]
        raise SystemExit(f'{source} does not exist')
    files = [source] if source.is_file() else sorted(p for p in source.rglob('*') if p.is_file() and not any(part.startswith('.') for part in p.relative_to(source).parts))
    if source.is_dir() and ((source / 'dataset_dict.json').exists() or (source / 'state.json').exists()):
        try:
            from datasets import load_from_disk
            ds = load_from_disk(str(source)); ds = ds if hasattr(ds, 'keys') else {'train': ds}
            return [], [], [(r, name) for name in ds for r in ds[name]]
        except ImportError: pass
    docs = [p for p in files if p.suffix.lower() in DOC_EXT and p.name not in SKIP_NAMES and not re.match(r'(readme|license|licence|changelog)\b', p.name, re.I)]
    tables = [p for p in files if p.suffix.lower() in TABLE_EXT and p.name not in SKIP_NAMES and 'import-ledger' not in p.name and p.name != 'dataset_info.json']
    return docs, tables, []


def run(args):
    source, out = Path(args.path), Path(args.out)
    if not args.dry_run:
        if out.exists() and any(out.iterdir()) and not args.force: raise SystemExit(f'{out} is not empty; pass --force to overwrite')
        if out.exists() and args.force: shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)
    bundle = Bundle(out, args); rep = bundle.report; override = kv(args.map)
    docs, tables, hub = collect(source, args)
    base = source if source.is_dir() else source.parent
    sidecar, qa_rows, mappings = {}, [], {}
    # tables: decide qa / document-rows / metadata-sidecar by mapped columns
    table_rows = [(r, str(p.relative_to(base)) if source.exists() else str(p)) for p in tables for r in read_table(p)] + [(r, f'hub:{s}') for r, s in hub]
    for m in ([source / 'manifest.jsonl'] if source.is_dir() else []):  # an existing LexiMind manifest supplies metadata
        if m.exists():
            for r in read_table(m):
                if isinstance(r.get('metadata'), dict) and r.get('path'):
                    sidecar[r['path'].replace('\\', '/').lower()] = {k: v for k, v in r['metadata'].items() if k not in {'corpus_id', 'corpus_version'}}
    groups = {}
    for row, origin in table_rows: groups.setdefault(origin, []).append(row)
    for origin, rows in groups.items():
        cols = mapping(list({k for r in rows[:200] for k in r}), override); mappings[origin] = cols
        if 'question' in cols: qa_rows += [(r, cols, origin) for r in rows]; rep['tables_qa'] += 1
        elif 'context' in cols:
            rep['tables_documents'] += 1
            for r in rows[:args.limit or None]:
                text = first_text(get(r, cols['context']))
                if text: bundle.add_text(text, first_text(get(r, cols['title'])) if 'title' in cols else None, doc_meta(r, cols), [first_text(get(r, cols['doc'])) if 'doc' in cols else None, first_text(get(r, cols['id'])) if 'id' in cols else None])
        elif 'doc' in cols:
            rep['tables_metadata'] += 1
            for r in rows: sidecar[str(first_text(get(r, cols['doc']))).replace('\\', '/').lower()] = doc_meta(r, cols)
        else: rep['tables_unrecognized'] += 1
    for p in docs[:args.limit or None]:
        rel = p.relative_to(base) if p != source else Path(p.name)
        meta = dict(sidecar.get(str(rel).replace('\\', '/').lower()) or sidecar.get(p.name.lower()) or sidecar.get(p.stem.lower()) or {})
        side = p.with_name(p.name + '.meta.json')
        if side.exists(): meta.update(json.loads(side.read_text(encoding='utf-8')))
        bundle.add_file(p, rel, meta)
    # QA rows -> eval items
    items, flagged, seen = [], [], set()
    workflow_default = args.workflow
    for row, cols, origin in qa_rows[:args.limit or None]:
        rep['qa_rows_read'] += 1
        question = first_text(get(row, cols['question']))
        if not question: rep['qa_rows_without_question'] += 1; continue
        ans_val = get(row, cols['answer']) if 'answer' in cols else None
        answer = first_text(ans_val)
        start = None
        if isinstance(ans_val, dict) and ans_val.get('answer_start'): start = ans_val['answer_start'][0] if isinstance(ans_val['answer_start'], list) else ans_val['answer_start']
        elif isinstance(ans_val, list) and ans_val and isinstance(ans_val[0], dict): start = ans_val[0].get('answer_start')
        elif 'answer_start' in cols: start = get(row, cols['answer_start'])
        try: start = int(start) if start not in (None, '') else None
        except (TypeError, ValueError): start = None
        rels = []
        refs = get(row, cols['doc']) if 'doc' in cols else None
        if isinstance(refs, str) and refs.strip().startswith('['):
            try: refs = json.loads(refs)
            except ValueError: pass
        for ref in (refs if isinstance(refs, list) else [refs] if refs else []):
            rel = bundle.resolve(ref)
            if rel: rels.append(rel)
            else: rep['qa_unresolved_document_refs'] += 1
        context_quotes = []
        if 'context' in cols:
            title = first_text(get(row, cols['title'])) if 'title' in cols else None
            for t, text in contexts(get(row, cols['context'])):
                # A passage that also names a real document is a supporting quote from it, not a new document.
                if rels and len(text) <= 3000 and any(locate(text, bundle.docs[r]['pages']) for r in rels): context_quotes.append(text); continue
                if rels and len(text) <= 3000: context_quotes.append(text); continue  # stays flagged if not locatable
                rels.append(bundle.add_text(text, t or title, {**doc_meta(row, cols), 'from_context': True}))
        if context_quotes and 'quote' not in cols and 'gold' not in cols: row = {**row, '__quote': context_quotes}; cols = {**cols, 'quote': '__quote'}
        rels = list(dict.fromkeys(rels))
        un = truthy(get(row, cols['unanswerable'])) if 'unanswerable' in cols else None
        ok = truthy(get(row, cols['answerable'])) if 'answerable' in cols else None
        answerable = (not un) if un is not None else ok if ok is not None else bool(answer)
        golds, gold_source = build_gold(bundle, row, cols, rels, answer, start) if answerable else ([], None)
        gold, spans, problems = [], [], []
        for rel, quote in golds:
            candidates = [rel] if rel else rels or list(bundle.docs)
            hit = next(((r, h) for r in candidates for h in [locate(quote, bundle.docs[r]['pages'])] if h), None)
            if not hit: problems.append('gold_quote_not_found'); continue
            r, (page, s, e, exact, level) = hit
            gold.append({'doc': r, 'quote': exact, 'page': page}); spans.append((r, page, s, e)); rep['gold_match_' + level] += 1
        if answerable and not gold and not problems: problems.append('no_gold_source')
        rels = list(dict.fromkeys(rels + [g['doc'] for g in gold]))
        explicit_split = first_text(get(row, cols['split'])) if 'split' in cols else (origin if re.search(r'test|heldout|held_out|valid|dev|train', origin, re.I) else None)
        rid = first_text(get(row, cols['id'])) if 'id' in cols else None
        rid = re.sub(r'\s+', '-', rid) if rid else 'q-' + sha(question + '|'.join(rels))[:12]
        while rid in seen: rid += '-dup'
        seen.add(rid)
        wf = (first_text(get(row, cols['workflow'])) or '').lower() if 'workflow' in cols else ''
        item = {'id': rid, 'split': None, 'workflow': wf if wf in {'chat', 'research', 'review', 'drafting'} else workflow_default,
                'question': question, 'documents': rels, 'gold': gold, 'answerable': answerable}
        if answer: item['reference_answer'] = answer
        kind = first_text(get(row, cols['kind'])) if 'kind' in cols else None
        if kind in {'fact', 'legal'}: item['kind'] = kind
        if gold_source: item['gold_source'] = gold_source
        item['_spans'], item['_explicit_split'] = spans, explicit_split
        if problems: item['flags'] = sorted(set(problems)); rep['eval_flag_' + item['flags'][0]] += 1
        items.append(item)
    # dedupe identical question+documents
    unique = {}
    for item in items:
        k = (qnorm(item['question']), tuple(item['documents']))
        if k in unique: rep['qa_duplicates_dropped'] += 1; continue
        unique[k] = item
    items = list(unique.values())
    # deterministic split
    group_by = args.group_by
    if group_by == 'auto': group_by = 'document' if len({tuple(i['documents']) for i in items}) >= 5 else 'id'
    for item in items:
        key = '|'.join(item['documents']) if group_by == 'document' and item['documents'] else item['id']
        item['split'] = split_of(None if args.ignore_source_splits else item['_explicit_split'], key, args.heldout_frac)
    held = [i for i in items if i['split'] == 'heldout']
    held_q = {sha(qnorm(i['question'])) for i in held}
    held_ctx = {sha(qnorm(g['quote'])) for i in held for g in i['gold']}
    held_docs = {d for i in held for d in i['documents']}
    # SFT from dev rows only
    sft, rejected = [], []
    for item in items:
        if item['split'] != 'dev' or item.get('flags'): continue
        if sha(qnorm(item['question'])) in held_q: rejected.append({'id': item['id'], 'reason': 'question_also_heldout'}); continue
        if any(sha(qnorm(g['quote'])) in held_ctx for g in item['gold']): rejected.append({'id': item['id'], 'reason': 'gold_passage_also_heldout'}); continue
        if set(item['documents']) & held_docs:
            rep['sft_rows_sharing_heldout_documents'] += 1
            if args.strict_doc_isolation: rejected.append({'id': item['id'], 'reason': 'shares_heldout_document'}); continue
        if not item['answerable'] and args.no_abstain: continue
        if item['answerable'] and not item.get('reference_answer') and item.get('gold_source') != 'explicit': rejected.append({'id': item['id'], 'reason': 'no_answer'}); continue
        ex, why = sft_example(bundle, item, item['_spans'], args)
        if why: rejected.append({'id': item['id'], 'reason': why}); continue
        sft.append(ex)
    held_ids = {i['id'] for i in held}
    assert not any(e['meta']['eval_id'] in held_ids for e in sft), 'held-out leak into SFT'
    for r in rejected: rep['sft_reject_' + r['reason']] += 1
    clean = lambda i: {k: v for k, v in i.items() if not k.startswith('_')}
    evals = [clean(i) for i in items if not i.get('flags') or args.keep_flagged]
    flagged = [clean(i) for i in items if i.get('flags')]
    manifest = [{'path': d['path'], 'sha256': d['sha256'], 'metadata': {k: v for k, v in d['metadata'].items() if k != 'from_context'} | ({'from_qa_context': True} if d['metadata'].get('from_context') else {})} for d in bundle.docs.values()]
    report = {'source': str(source), 'out': str(out), 'dry_run': args.dry_run, 'group_by': group_by, 'heldout_frac': args.heldout_frac,
              'documents': len(manifest), 'document_parse_failures': bundle.failures, 'documents_exceeding_app_limits': bundle.limits,
              'eval_rows': len(evals), 'eval_dev': sum(i['split'] == 'dev' for i in evals), 'eval_heldout': sum(i['split'] == 'heldout' for i in evals),
              'eval_unanswerable': sum(not i['answerable'] for i in evals), 'eval_flagged': len(flagged),
              'sft_rows': len(sft), 'sft_abstain_rows': sum(e['meta']['abstain'] for e in sft), 'sft_rejected': len(rejected),
              'heldout_leak_check': 'passed', 'column_mappings': mappings, 'counts': dict(sorted(rep.items()))}
    if len(manifest) > 200: report['warning'] = 'The app prototype holds 200 documents per tenant; import a subset or split across tenants.'
    if not args.dry_run:
        def dump(name, rows):
            with (out / name).open('w', encoding='utf-8') as f:
                for r in rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
        dump('manifest.jsonl', manifest); dump('eval.jsonl', evals); dump('sft.jsonl', sft)
        dump('eval_flagged.jsonl', flagged); dump('sft_rejected.jsonl', rejected)
        (out / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('path'); p.add_argument('--out', required=True)
    p.add_argument('--heldout-frac', type=float, default=0.3)
    p.add_argument('--group-by', choices=['auto', 'id', 'document'], default='auto', help='split unit; document keeps all questions about a document in one split')
    p.add_argument('--ignore-source-splits', action='store_true', help='ignore split columns / test-file names and hash everything')
    p.add_argument('--strict-doc-isolation', action='store_true', help='drop SFT rows whose documents also appear in held-out rows')
    p.add_argument('--map', default='', help='field=column overrides, e.g. question=Query,answer=Ans,context=meta.text,doc=file')
    p.add_argument('--metadata-defaults', default='', help='e.g. jurisdiction=IN,document_type=judgment (used when not inferred/provided)')
    p.add_argument('--workflow', default='chat', choices=['chat', 'research', 'review', 'drafting'])
    p.add_argument('--corpus-id'); p.add_argument('--corpus-version', default=date.today().isoformat())
    p.add_argument('--min-overlap', type=float, default=0.6, help='min fraction of answer terms present in cited lines for SFT')
    p.add_argument('--no-abstain', action='store_true', help='do not emit empty-answer SFT rows for unanswerable questions')
    p.add_argument('--keep-flagged', action='store_true', help='also write flagged rows (unverified gold) into eval.jsonl')
    p.add_argument('--skip-ocr', action='store_true', help='do not OCR scanned pages (faster; pages stay empty)')
    p.add_argument('--limit', type=int); p.add_argument('--dry-run', action='store_true'); p.add_argument('--force', action='store_true')
    args = p.parse_args(argv)
    if args.skip_ocr:
        def no_ocr(image): raise RuntimeError('OCR skipped')
        parsing.ocr_image = no_ocr
    report = run(args)
    summary = {k: v for k, v in report.items() if k not in {'column_mappings'}}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return report


if __name__ == '__main__':
    main()
