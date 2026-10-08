"""Local legal retrieval: BM25 + dense (LSA or pluggable neural embedder) + exact legal-term
matching, fused with reciprocal ranks over deterministic query rewrites, optional LLM rerank.

Modes (ablation ladder; `search(..., mode=)` or env LEXIMIND_RETRIEVAL_MODE):
  bm25            sparse only
  lsa             corpus-fitted LSA dense only
  hybrid          the original v1 pipeline (BM25 + LSA + RRF), kept bit-for-bit as reference
  hybrid+rewrite  hybrid over legal query variants (section/act normalisation, CrPC<->BNSS...)
  full            hybrid+rewrite + exact section/citation boost + neural embeddings when
                  configured (LEXIMIND_EMBEDDINGS) + optional LLM rerank (LEXIMIND_RERANK=llm)
LSA is a corpus-trained dense baseline, not a pretrained legal embedding model.
Only ciphertext is stored on disk; matrices are derived in memory per tenant and cached
in-process (bounded) keyed by the pool's chunk ids + text hashes.
"""
import hashlib
import math
import os
import re
from collections import Counter, OrderedDict

import numpy as np

from backend.query_rewrite import parse_query, rewrite_with_llm

STOP = set('the a an is are to of in and or for on by with as be it this that from'.split())
MODES = ('bm25', 'lsa', 'hybrid', 'hybrid+rewrite', 'full')
K = 60
DENSE_WEIGHT = float(os.getenv("LEXIMIND_DENSE_WEIGHT", "0.7"))


def terms(text):
    text = re.sub(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])', ' ', text)
    return [t for t in re.findall(r'\w+', text.casefold()) if t not in STOP and len(t) > 1]


class _LRU(OrderedDict):
    def __init__(self, size):
        super().__init__()
        self.size = size

    def get_or(self, key, build):
        if key in self:
            self.move_to_end(key)
            return self[key]
        value = self[key] = build()
        while len(self) > self.size:
            self.popitem(last=False)
        return value


_TERM_CACHE = _LRU(20000)
_INDEX_CACHE = _LRU(8)


def _digest(text):
    return hashlib.blake2b(text.encode('utf-8', 'ignore'), digest_size=16).digest()


def _counts(text):
    return _TERM_CACHE.get_or(_digest(text), lambda: Counter(terms(text)))


# ---------------------------------------------------------------- legacy v1 ('hybrid') ----
def _legacy(chunks, query, limit=10):
    if not chunks:
        return []
    counts = [Counter(_counts(c['text'])) for c in chunks]
    query_terms = Counter(terms(query))
    if not query_terms:
        return []
    n = len(counts)
    df = Counter(t for count in counts for t in count)
    # OCR can omit spaces: recover query terms inside recognized runs for sparse retrieval.
    for count in counts:
        for term in query_terms:
            if len(term) >= 4 and not count[term]:
                count[term] = sum(value for token, value in list(count.items()) if term in token and len(token) > len(term)) * .5
                if count[term]:
                    df[term] += 1
    average = sum(sum(c.values()) for c in counts) / max(n, 1)
    lexical = []
    for count in counts:
        length = sum(count.values())
        score = sum(math.log(1 + (n - df[t] + .5) / (df[t] + .5)) * count[t] * 2.2 / (count[t] + 1.2 * (.25 + .75 * length / max(average, 1))) for t in query_terms if count[t])
        lexical.append(score)
    vocabulary = sorted(df, key=lambda t: (-df[t], t))[:2048]
    columns = {t: i for i, t in enumerate(vocabulary)}
    matrix = np.zeros((n, len(vocabulary)), dtype=np.float32)
    vector = np.zeros(len(vocabulary), dtype=np.float32)
    for term, column in columns.items():
        idf = math.log((1 + n) / (1 + df[term])) + 1
        for row, count in enumerate(counts):
            if count[term]:
                matrix[row, column] = (1 + math.log(count[term])) * idf
        if query_terms[term]:
            vector[column] = (1 + math.log(query_terms[term])) * idf
    dense = np.zeros(n)
    if matrix.size and np.linalg.norm(vector):
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        normalized = matrix / np.maximum(norms, 1e-8)
        rank = min(64, n, len(vocabulary))
        if rank < min(n, len(vocabulary)):
            rng = np.random.default_rng(42)
            projection = normalized @ rng.standard_normal((len(vocabulary), rank)).astype(np.float32)
            basis, _ = np.linalg.qr(projection)
            _, _, vt = np.linalg.svd(basis.T @ normalized, full_matrices=False)
        else:
            _, _, vt = np.linalg.svd(normalized, full_matrices=False)
        latent = normalized @ vt[:rank].T
        q = vector @ vt[:rank].T
        dense = (latent @ q) / np.maximum(np.linalg.norm(latent, axis=1) * np.linalg.norm(q), 1e-8)
    ranks = {}
    for scores in (lexical, dense):
        for rank, index in enumerate(sorted(range(n), key=lambda i: (-float(scores[i]), chunks[i]['id'])), 1):
            if scores[index] > 1e-6:
                ranks[index] = ranks.get(index, 0) + 1 / (K + rank)
    selected = sorted(ranks, key=lambda i: (-ranks[i], -lexical[i], chunks[i]['id']))[:limit]
    qset = set(query_terms)
    return [{**chunks[i], 'score': round(ranks[i], 6), 'lexical_score': round(lexical[i], 4), 'dense_score': round(float(dense[i]), 4),
             'retrieval_mode': 'hybrid', 'matched_terms': sorted(qset & set(_counts(chunks[i]['text']))), 'dense_method': 'lsa'} for i in selected]


# ---------------------------------------------------------------- cached pool index ------
class _Index:
    def __init__(self, chunks):
        self.ids = [c['id'] for c in chunks]
        self.texts = [c['text'] for c in chunks]
        self.counts = [_counts(t) for t in self.texts]
        self.n = n = len(chunks)
        self.lengths = np.array([sum(c.values()) for c in self.counts], dtype=np.float64)
        self.avg = max(float(self.lengths.mean()) if n else 1.0, 1.0)
        self.postings = {}
        for row, count in enumerate(self.counts):
            for t, v in count.items():
                self.postings.setdefault(t, []).append((row, v))
        self.df = {t: len(p) for t, p in self.postings.items()}
        self._super = {}
        self._flat = None
        vocab = sorted(self.df, key=lambda t: (-self.df[t], t))[:2048]
        self.columns = {t: i for i, t in enumerate(vocab)}
        self.idf = np.array([math.log((1 + n) / (1 + self.df[t])) + 1 for t in vocab], dtype=np.float32)
        matrix = np.zeros((n, len(vocab)), dtype=np.float32)
        for t, col in self.columns.items():
            for row, v in self.postings[t]:
                matrix[row, col] = (1 + math.log(v)) * self.idf[col]
        self.latent = None
        if matrix.size:
            normalized = matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8)
            rank = min(64, n, len(vocab))
            if rank < min(n, len(vocab)):
                projection = normalized @ np.random.default_rng(42).standard_normal((len(vocab), rank)).astype(np.float32)
                basis, _ = np.linalg.qr(projection)
                _, _, vt = np.linalg.svd(basis.T @ normalized, full_matrices=False)
            else:
                _, _, vt = np.linalg.svd(normalized, full_matrices=False)
            self.vt = vt[:rank]
            latent = normalized @ self.vt.T
            self.latent = latent / np.maximum(np.linalg.norm(latent, axis=1, keepdims=True), 1e-8)

    def supersets(self, term):
        # OCR can omit spaces: tokens that contain the query term (weighted .5 in BM25).
        if term not in self._super:
            self._super[term] = [t for t in self.postings if term in t and len(t) > len(term)] if len(term) >= 4 else []
        return self._super[term]

    def bm25(self, query_terms):
        scores = np.zeros(self.n)
        norm = 1.2 * (.25 + .75 * self.lengths / self.avg)
        for t in query_terms:
            tf = np.zeros(self.n)
            for row, v in self.postings.get(t, ()):
                tf[row] = v
            extra = self.supersets(t)
            if extra:
                rec = np.zeros(self.n)
                for s in extra:
                    for row, v in self.postings[s]:
                        rec[row] += v
                tf = np.where(tf > 0, tf, rec * .5)
            df = int((tf > 0).sum())
            if not df:
                continue
            idf = math.log(1 + (self.n - df + .5) / (df + .5))
            scores += idf * tf * 2.2 / (tf + norm)
        return scores

    def lsa(self, query_terms):
        if self.latent is None:
            return np.zeros(self.n)
        vector = np.zeros(len(self.columns), dtype=np.float32)
        for t, v in query_terms.items():
            if t in self.columns:
                vector[self.columns[t]] = (1 + math.log(v)) * self.idf[self.columns[t]]
        if not np.linalg.norm(vector):
            return np.zeros(self.n)
        q = vector @ self.vt.T
        return (self.latent @ q) / max(float(np.linalg.norm(q)), 1e-8)

    def flat(self):
        if self._flat is None:
            self._flat = [re.sub(r'\s+', '', t).casefold() for t in self.texts]
        return self._flat


def _index(chunks):
    h = hashlib.blake2b(digest_size=16)
    for c in chunks:
        h.update(str(c['id']).encode())
        h.update(_digest(c['text']))
    return _INDEX_CACHE.get_or(h.digest(), lambda: _Index(chunks))


# ---------------------------------------------------------------- exact legal terms ------
_ACT_HINTS = None


def _act_patterns():
    global _ACT_HINTS
    if _ACT_HINTS is None:
        from backend.legal_aliases import ACTS
        _ACT_HINTS = {k: re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(a) for a in aliases) + r')(?!\w)', re.I) for k, (_, aliases) in ACTS.items()}
    return _ACT_HINTS


def exact_scores(index, parsed):
    """Per-chunk score for statute headings ('438. Direction ...'), 'Section 438' mentions
    (with act context) and normalised neutral/reporter citations. Returns (scores, matched)."""
    scores, matched = np.zeros(index.n), [[] for _ in range(index.n)]
    acts = _act_patterns()
    direct = set(parsed.direct)
    for act, num in parsed.provisions:
        factor = 1.0 if (act, num) in direct else 0.4  # concept/alias-derived provisions count less
        n = re.escape(num)
        art = act == 'coi'
        heading = re.compile(r'(?m)^\s*' + n + r'\s?\.\s*[A-Z“"][^\n]{0,200}')
        mention = re.compile((r'(?i)\b(?:article|art\.)\s*' if art else r'(?i)(?:\bsections?|\bsecs?\.|\bs\.|\bu/s\.?)\s*(?:\d{1,4}[A-Z]{0,2}(?:\(\w+\))*\s*(?:/|,|or|and|&)\s*)*') + n + r'(?![\dA-Za-z])')
        label = f'{"article" if art else "section"} {num.lower()}' + (f' ({act})' if act else '')
        found = False
        for row, text in enumerate(index.texts):
            s = 0.0
            h = heading.search(text)
            if h and not art:
                s = 3.0 if re.search(r'[—–]|\.-', h.group(0)) else 1.5
            if mention.search(text):
                s = max(s, 2.0)
            if s and act and act in acts and acts[act].search(text):
                s += 1.0
            if s:
                found = True
                scores[row] += s * factor
                matched[row].append(label)
        if not found and act in acts and (act, num) in direct:
            # Section absent from the pool: weak credit for chunks that at least name the act.
            for row, text in enumerate(index.texts):
                if acts[act].search(text):
                    scores[row] += 1.0
                    matched[row].append(f'act:{act}')
    for cite in parsed.entities.get('citations', []):
        key = re.sub(r'\s+', '', cite)
        for row, flat in enumerate(index.flat()):
            if key in flat:
                scores[row] += 4.0
                matched[row].append(cite)
    return scores, matched


# ---------------------------------------------------------------- fusion -----------------
def _rrf(fused, scores, ids, weight=1.0):
    order = sorted(range(len(ids)), key=lambda i: (-float(scores[i]), ids[i]))
    for rank, i in enumerate(order, 1):
        if scores[i] > 1e-6:
            fused[i] = fused.get(i, 0) + weight / (K + rank)


def _dense_neural(embedder, index, variants):
    vectors = embedder.embed(index.texts)
    qv = embedder.embed(variants)
    return [vectors @ q for q in qv]


def _modern(chunks, query, limit, mode, rewrite, embedder, reranker, llm):
    if not chunks or not terms(query):
        return []
    index = _index(chunks)
    parsed = parse_query(query) if rewrite and mode in ('hybrid+rewrite', 'full') else None
    variants = parsed.variants if parsed else [query]
    if parsed and llm is not None and (rewrite == 'llm' or os.getenv('LEXIMIND_QUERY_REWRITE', '').lower() == 'llm'):
        variants = list(dict.fromkeys(variants + rewrite_with_llm(query, llm)))
    variants = [v for v in variants if terms(v)]
    qterms = [Counter(terms(v)) for v in variants]
    fused, dense_method = {}, 'none' if mode == 'bm25' else 'lsa'
    lexical = [index.bm25(q) for q in qterms] if mode != 'lsa' else [np.zeros(index.n)]
    dense = [np.zeros(index.n)]
    if mode != 'bm25':
        dense = None
        if mode == 'full':
            from backend.embeddings import get_embedder
            emb = embedder if embedder is not None else get_embedder()
            if emb is not None:
                try:
                    dense, dense_method = _dense_neural(emb, index, variants), getattr(emb, 'name', 'embedder')
                except Exception:
                    dense, dense_method = None, 'lsa (embedder failed)'
        if dense is None:
            dense = [index.lsa(q) for q in qterms]
    for v in range(len(variants)):
        w = 1.0 if v == 0 else 0.5
        if mode != 'lsa':
            _rrf(fused, lexical[v], index.ids, w)
        if mode != 'bm25':
            _rrf(fused, dense[v], index.ids, w * DENSE_WEIGHT)
    matched = [[] for _ in range(index.n)]
    if mode == 'full' and parsed and (parsed.provisions or parsed.entities['citations']):
        ex, matched = exact_scores(index, parsed)
        # Specific references (few matching chunks) get full weight; a section quoted on every
        # page of a judgment should not drown the topical signal.
        hits = int((ex > 0).sum())
        _rrf(fused, ex, index.ids, 2.0 * min(1.0, 3 / max(hits, 1)))
    best_lex = np.max(np.vstack(lexical), axis=0)
    selected = sorted(fused, key=lambda i: (-fused[i], -best_lex[i], index.ids[i]))
    rr = reranker
    if rr is None and mode == 'full':
        from backend.rerank import get_reranker
        rr = get_reranker(llm)
    depth = max(limit, getattr(rr, 'top_n', 0)) if rr else limit
    qset = set().union(*qterms) if qterms else set()
    results = [{**chunks[i], 'score': round(fused[i], 6), 'lexical_score': round(float(lexical[0][i]), 4), 'dense_score': round(float(dense[0][i]), 4),
                'retrieval_mode': mode, 'matched_terms': sorted(qset & set(index.counts[i])) + matched[i], 'dense_method': dense_method} for i in selected[:depth]]
    if rr:
        results, used = rr.rerank(query, results, limit)
        for r in results:
            r['retrieval_mode'] = mode + ('+rerank' if used else '')
    return results[:limit]


def search(chunks, query, limit=10, *, mode=None, rewrite=True, embedder=None, reranker=None, llm=None):
    mode = (mode or os.getenv('LEXIMIND_RETRIEVAL_MODE') or 'full').lower()
    if mode not in MODES:
        mode = 'full'
    if mode == 'hybrid':
        return _legacy(chunks, query, limit)
    return _modern(chunks, query, limit, mode, rewrite, embedder, reranker, llm)


RETRIEVERS = {m: (lambda m: lambda chunks, query, limit=10: search(chunks, query, limit, mode=m))(m) for m in MODES}

METHOD = {'bm25': 'bm25-v2', 'lsa': 'lsa-v2', 'hybrid': 'bm25-lsa-rrf-v1', 'hybrid+rewrite': 'bm25-lsa-rrf+legal-rewrite-v2', 'full': 'bm25-dense-exact-rrf+legal-rewrite-v2'}
