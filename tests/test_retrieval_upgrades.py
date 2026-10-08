import importlib.util
from pathlib import Path

import pytest

from backend import retrieval
from backend.embeddings import Embedder, get_embedder
from backend.query_rewrite import parse_query, rewrite_with_llm
from backend.rerank import LLMReranker
from backend.retrieval import RETRIEVERS, search

_spec = importlib.util.spec_from_file_location('retrieval_v1', Path(__file__).parent / 'fixtures' / 'retrieval_v1_reference.py')
v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v1)

POOL = [
    {'id': 'bnss-482', 'document_id': 'bnss', 'text': '482. Direction for grant of bail to person apprehending arrest.—(1) Where any person has reason to believe that he may be arrested on an accusation of having committed a non-bailable offence, he may apply to the High Court or the Court of Session.'},
    {'id': 'crpc-438', 'document_id': 'crpc', 'text': '438. Direction for grant of bail to person apprehending arrest.—(1) When any person has reason to believe that he may be arrested on accusation of having committed a non-bailable offence.'},
    {'id': 'judgment', 'document_id': 'sc', 'text': 'In Bharat Chaudhary v. State of Bihar reported in (2003) 8 SCC 77, this Court held that charge sheet filing is no bar. See also 2026 INSC 145.'},
    {'id': 'contract-73', 'document_id': 'ica', 'text': '73. Compensation for loss or damage caused by breach of contract.—When a contract has been broken, the party who suffers by such breach is entitled to receive compensation.'},
    {'id': 'contract-27', 'document_id': 'ica', 'text': '27. Agreement in restraint of trade, void.—Every agreement by which any one is restrained from exercising a lawful profession, trade or business is void.'},
    {'id': 'noise-1', 'document_id': 'x', 'text': 'The accused was arrested at 10 pm and produced before the Magistrate with the bail bond of Rs. 50,000.'},
    {'id': 'noise-2', 'document_id': 'x', 'text': 'Agreements void for uncertainty are not enforceable. The party may claim damages for breach in some cases.'},
]


@pytest.mark.parametrize('q', ['s. 438 CrPC', 'S.438 CrPC', 'sec 438 crpc', 'u/s 438 Cr.P.C.', 'section 438(1) CrPC', 'Sec. 438 CrPC'])
def test_section_normalisation(q):
    p = parse_query(q)
    assert p.entities['sections'] == ['438']
    assert ('crpc', '438') in p.provisions and ('bnss', '482') in p.provisions
    assert 'section 438' in p.exact_terms and 'section 482' in p.exact_terms
    assert any('section 438' in v for v in p.variants[1:])


def test_articles_citations_and_entities():
    p = parse_query('Art. 21 and Sumit v. State of U P, 2026 INSC 145, (2011) 1 SCC 694, Rs. 50,000/- on 07.01.2026 before the High Court')
    assert p.entities['articles'] == ['21'] and 'article 21' in p.exact_terms
    assert {'2026 insc 145', '(2011) 1 scc 694'} <= set(p.exact_terms)
    assert p.entities['dates'] == ['07.01.2026'] and p.entities['amounts'] and p.entities['courts'] and p.entities['parties']
    assert parse_query('IPC 302').provisions == [] and parse_query('s. 302 IPC').provisions[-1] == ('bns', '103')


def test_old_new_code_alias_retrieval_both_directions():
    assert search(POOL, 'anticipatory bail Section 438 CrPC', 3, mode='full')[0]['id'] in {'crpc-438', 'bnss-482'}
    hits = [h['id'] for h in search(POOL, 'Section 438 CrPC', 2, mode='full')]
    assert 'bnss-482' in hits
    hits = [h['id'] for h in search(POOL, 'Section 482 BNSS', 2, mode='full')]
    assert 'crpc-438' in hits
    # Only the BNSS text is indexed: the alias still finds it for an old-code query.
    only_new = [c for c in POOL if c['id'] != 'crpc-438']
    top = search(only_new, 'Section 438 CrPC', 1, mode='full')[0]
    assert top['id'] == 'bnss-482' and any('482' in t for t in top['matched_terms'])


def test_exact_citation_boost():
    top = search(POOL, '(2003) 8 SCC 77', 3, mode='full')[0]
    assert top['id'] == 'judgment' and '(2003) 8 scc 77' in top['matched_terms']
    assert search(POOL, 'sec 73 ICA', 1, mode='full')[0]['id'] == 'contract-73'


def test_hybrid_mode_reproduces_v1_exactly():
    pool = POOL * 1 + [{'id': f'pad-{i}', 'document_id': 'p', 'text': f'padding text {i} about bail contract arrest {"x" * i}'} for i in range(80)]
    for q in ['anticipatory bail', 'breach of contract compensation', 'restraint of trade', 'arrest 438', 'zzz']:
        old = v1.search(pool, q, 10)
        new = search(pool, q, 10, mode='hybrid')
        assert [(h['id'], h['score'], h['lexical_score'], h['dense_score']) for h in old] == [(h['id'], h['score'], h['lexical_score'], h['dense_score']) for h in new]


@pytest.mark.parametrize('mode', ['bm25', 'lsa', 'hybrid', 'hybrid+rewrite', 'full'])
def test_output_keys_backward_compatible(mode):
    hits = search(POOL, 'bail arrest', 5, mode=mode)
    assert hits and len(hits) <= 5
    for h in hits:
        assert {'id', 'document_id', 'text', 'score', 'lexical_score', 'dense_score', 'retrieval_mode', 'matched_terms', 'dense_method'} <= set(h)
    assert search(POOL, 'bail arrest', 5, mode=mode) == hits  # deterministic
    assert RETRIEVERS[mode](POOL, 'bail arrest', 5) == hits
    assert search([], 'bail', mode=mode) == [] and search(POOL, '  ', mode=mode) == []


def test_default_mode_env(monkeypatch):
    monkeypatch.setenv('LEXIMIND_RETRIEVAL_MODE', 'bm25')
    assert search(POOL, 'bail', 3)[0]['retrieval_mode'] == 'bm25'
    monkeypatch.delenv('LEXIMIND_RETRIEVAL_MODE')
    monkeypatch.delenv('LEXIMIND_EMBEDDINGS', raising=False)
    assert search(POOL, 'bail', 3)[0]['retrieval_mode'] == 'full'


class Broken(Embedder):
    name = 'broken'

    def _embed(self, texts):
        raise ConnectionError('no server')


class Fake(Embedder):
    name = 'fake'

    def _embed(self, texts):
        self.calls = getattr(self, 'calls', 0) + 1
        return [[t.count('bail') + .1, t.count('contract') + .1, len(t) % 7 + .1] for t in texts]


def test_embedder_failure_falls_back_to_lsa():
    hits = search(POOL, 'bail', 3, mode='full', embedder=Broken())
    assert hits and hits[0]['dense_method'].startswith('lsa')
    assert get_embedder('nonsense') is None and get_embedder('lsa') is None


def test_neural_embedder_used_and_cached():
    fake = Fake()
    hits = search(POOL, 'bail', 3, mode='full', embedder=fake)
    assert hits[0]['dense_method'] == 'fake'
    calls = fake.calls
    search(POOL, 'bail', 3, mode='full', embedder=fake)
    assert fake.calls == calls  # chunk + query vectors served from cache


class LLM:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def complete(self, messages, schema):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result(messages) if callable(self.result) else self.result


def _ranked(n=10):
    return [{'id': f'c{i}', 'text': f'text {i}'} for i in range(n)]


def test_reranker_failure_falls_back():
    ranked = _ranked()
    out, used = LLMReranker(LLM(error=TimeoutError())).rerank('q', ranked, 5)
    assert not used and [c['id'] for c in out] == ['c0', 'c1', 'c2', 'c3', 'c4']
    out, used = LLMReranker(LLM(result={'scores': []})).rerank('q', _ranked(), 5)
    assert not used
    hits = search(POOL, 'bail', 3, mode='full', reranker=LLMReranker(LLM(error=ValueError())))
    assert hits[0]['retrieval_mode'] == 'full'


def test_reranker_keeps_first_stage_top3_and_reorders():
    # LLM loves the tail and hates the head.
    llm = LLM(result={'scores': [{'id': str(i), 'relevance': 3 if i >= 5 else 0} for i in range(10)]})
    out, used = LLMReranker(llm, protect=3).rerank('q', _ranked(), 5)
    ids = [c['id'] for c in out]
    assert used and len(ids) == 5 and {'c0', 'c1', 'c2'} <= set(ids)
    assert ids[:2] == ['c5', 'c6']
    # Ties broken by first-stage rank.
    out, _ = LLMReranker(LLM(result={'scores': [{'id': str(i), 'relevance': 1} for i in range(10)]})).rerank('q', _ranked(), 4)
    assert [c['id'] for c in out] == ['c0', 'c1', 'c2', 'c3']


def test_rerank_via_search_and_env(monkeypatch):
    llm = LLM(result=lambda m: {'scores': [{'id': '0', 'relevance': 3}]})
    monkeypatch.setenv('LEXIMIND_RERANK', 'llm')
    hits = search(POOL, 'bail arrest', 3, mode='full', llm=llm)
    assert llm.calls == 1 and hits[0]['retrieval_mode'] == 'full+rerank'


def test_llm_rewrite_hook_is_optional():
    assert rewrite_with_llm('bail', None) == []
    assert rewrite_with_llm('bail', LLM(error=RuntimeError())) == []
    assert rewrite_with_llm('bail', LLM(result={'variants': ['a', ' ', 'b', 'c', 'd']})) == ['a', 'b', 'c']
    llm = LLM(result={'variants': ['restraint of trade agreement void']})
    hits = search(POOL, 'noncompete covenant', 2, mode='full', rewrite='llm', llm=llm)
    assert llm.calls == 1 and hits[0]['id'] == 'contract-27'


def test_index_cache_reused():
    retrieval._INDEX_CACHE.clear()
    search(POOL, 'bail', 3, mode='full')
    search(POOL, 'contract', 3, mode='full')
    assert len(retrieval._INDEX_CACHE) == 1
    search(POOL[:-1], 'bail', 3, mode='full')
    assert len(retrieval._INDEX_CACHE) == 2
