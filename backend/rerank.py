"""Optional LLM pointwise rerank of first-stage candidates (off by default: CPU latency).

High-recall bias: first-stage top-`protect` candidates are never pushed out of the returned
list; ties are broken by first-stage rank; any failure returns the first-stage order."""
import os

RERANK_SCHEMA = {
    'type': 'object',
    'properties': {'scores': {'type': 'array', 'items': {'type': 'object', 'properties': {
        'id': {'type': 'string'}, 'relevance': {'type': 'integer', 'minimum': 0, 'maximum': 3}},
        'required': ['id', 'relevance'], 'additionalProperties': False}}},
    'required': ['scores'], 'additionalProperties': False}


class LLMReranker:
    def __init__(self, llm, top_n=20, protect=3, snippet=700):
        self.llm, self.top_n, self.protect, self.snippet = llm, top_n, protect, snippet

    def scores(self, query, candidates):
        listing = '\n\n'.join(f'[{i}] {c["text"][:self.snippet]}' for i, c in enumerate(candidates))
        out = self.llm.complete([
            {'role': 'system', 'content': 'You grade retrieved passages for an Indian legal research query. For every passage id give relevance 0 (irrelevant), 1 (topical), 2 (partially answers) or 3 (directly answers / is the cited provision). Judge only the passage text. Return JSON only.'},
            {'role': 'user', 'content': f'Query: {query[:1500]}\n\nPassages:\n{listing}'}], RERANK_SCHEMA)
        result = {}
        for row in (out or {}).get('scores', []):
            try:
                i = int(str(row['id']).strip('[] '))
                if 0 <= i < len(candidates):
                    result[i] = max(0, min(3, int(row['relevance'])))
            except (KeyError, TypeError, ValueError):
                continue
        if not result:
            raise ValueError('Reranker returned no usable scores.')
        return result

    def rerank(self, query, ranked, limit):
        """ranked: first-stage list of chunk dicts (best first). Returns (list, used: bool)."""
        head, tail = ranked[:self.top_n], ranked[self.top_n:]
        try:
            graded = self.scores(query, head)
        except Exception:
            return ranked[:limit], False
        order = sorted(range(len(head)), key=lambda i: (-graded.get(i, 0), i))
        out = [head[i] for i in order][:limit]
        # Never drop first-stage top-k: swap them back in for the weakest reranked items.
        missing = [head[i] for i in range(min(self.protect, len(head))) if head[i] not in out]
        if missing:
            out = [c for c in out if c not in missing][:max(0, limit - len(missing))]
            out = sorted(out + missing, key=lambda c: (-graded.get(head.index(c), 0), head.index(c)))
        for c in out:
            c['rerank_score'] = graded.get(head.index(c))
        return (out + tail)[:limit], True


def get_reranker(llm=None, enabled=None):
    on = enabled if enabled is not None else os.getenv('LEXIMIND_RERANK', '').lower() == 'llm'
    if not on or llm is None:
        return None
    return LLMReranker(llm, top_n=int(os.getenv('LEXIMIND_RERANK_TOP_N', '20')))
