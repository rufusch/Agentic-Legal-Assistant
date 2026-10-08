"""Pluggable retrievers for ablations plus LLM-free retrieval metrics against gold chunk ids.

Every retriever has the signature fn(chunks, query, limit) -> ranked chunk dicts. The default
('hybrid') is the production backend.retrieval.search, called with positional args only so
that kwargs added for ablations elsewhere do not break this harness.
"""
import importlib
import math
from collections import Counter

from backend import retrieval


def _mode(name):
    """Pin a retrieval mode explicitly so ablation names never drift with the env default."""
    def run(chunks, query, limit=10):
        return retrieval.search(chunks, query, limit, mode=name)
    return run


def hybrid(chunks, query, limit=10):
    return retrieval.search(chunks, query, limit, mode='hybrid')


def _rerank_production(field):
    """Rank by one component score of the production retriever (all candidates, then sort)."""
    def run(chunks, query, limit=10):
        rows = retrieval.search(chunks, query, len(chunks), mode='hybrid')
        if not rows or field not in rows[0]:
            raise RuntimeError(f'backend.retrieval.search no longer exposes {field}')
        return sorted((r for r in rows if r[field] > 1e-6), key=lambda r: (-r[field], r['id']))[:limit]
    return run


def bm25_plain(chunks, query, limit=10, k1=1.2, b=.75):
    """Textbook Okapi BM25 over backend.retrieval.terms, without the OCR-run recovery or dense fusion."""
    docs = [Counter(retrieval.terms(c['text'])) for c in chunks]
    q = set(retrieval.terms(query))
    if not docs or not q:
        return []
    n = len(docs); avg = sum(sum(d.values()) for d in docs) / n
    df = Counter(t for d in docs for t in d)
    scores = []
    for d in docs:
        length = sum(d.values())
        scores.append(sum(math.log(1 + (n - df[t] + .5) / (df[t] + .5)) * d[t] * (k1 + 1) / (d[t] + k1 * (1 - b + b * length / max(avg, 1))) for t in q if d[t]))
    order = sorted((i for i in range(n) if scores[i] > 0), key=lambda i: (-scores[i], chunks[i]['id']))[:limit]
    return [{**chunks[i], 'score': round(scores[i], 4)} for i in order]


RETRIEVERS = {
    'hybrid': hybrid,                          # production BM25 + LSA, reciprocal-rank fused
    'bm25': _rerank_production('lexical_score'),  # production lexical component only
    'dense': _rerank_production('dense_score'),   # production LSA component only
    'bm25_plain': bm25_plain,                  # textbook BM25 reference
}
# Every mode the production retriever exposes (bm25, lsa, hybrid, hybrid+rewrite, full)
# becomes an ablation arm under its own name.
RETRIEVERS.update({name: _mode(name) for name in getattr(retrieval, 'MODES', ()) if name not in RETRIEVERS})


def get(name):
    """Name from RETRIEVERS, or 'package.module:function' for variants added elsewhere."""
    if name in RETRIEVERS:
        return RETRIEVERS[name]
    if ':' in name:
        module, attr = name.split(':', 1)
        return getattr(importlib.import_module(module), attr)
    raise KeyError(f'Unknown retriever {name!r}; choose from {sorted(RETRIEVERS)} or module:function')


def budgeted(hits, characters=18000):
    """Same context budget as backend/chat.py: keep ranked chunks while they fit."""
    kept, size = [], 0
    for c in hits:
        if size + len(c['text']) <= characters:
            kept.append(c); size += len(c['text'])
    return kept


def ranking_metrics(ranked_ids, gold_ids, k):
    gold = set(gold_ids)
    top = ranked_ids[:k]
    hits = [i for i, cid in enumerate(top) if cid in gold]
    dcg = sum(1 / math.log2(i + 2) for i in hits)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(gold), k)))
    first = next((i for i, cid in enumerate(ranked_ids) if cid in gold), None)
    return {f'recall@{k}': len({top[i] for i in hits}) / len(gold), 'mrr': 1 / (first + 1) if first is not None else 0.0,
            f'ndcg@{k}': dcg / ideal if ideal else 0.0}


def evaluate_retrievers(queries, names, ks=(5, 10)):
    """Retrieval table per retriever and split. Only answerable queries with gold chunks are scored."""
    table = {}
    for name in names:
        fn = get(name)
        per_split = {}
        for q in queries:
            if not q['gold_chunk_ids']:
                continue
            ranked = [c['id'] for c in fn(q['chunks'], q['question'], max(ks))]
            row = {}
            for k in ks:
                row.update(ranking_metrics(ranked, q['gold_chunk_ids'], k))
            for split in ('all', q['split']):
                per_split.setdefault(split, []).append(row)
        table[name] = {split: {'queries': len(rows), **{m: round(sum(r[m] for r in rows) / len(rows), 4) for m in rows[0]}}
                       for split, rows in per_split.items()}
    return table
