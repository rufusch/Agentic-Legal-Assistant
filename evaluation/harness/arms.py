"""Evaluation arms. Each returns a prediction: claims with citations, retrieved chunk ids and latency.

Citation shape: {'source_id', 'quote', 'chunk_id'}; quote is '' when the model cited an id it was never shown.
"""
import json
import os
import time
from dataclasses import replace
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.chat import CHECK, SYSTEM, Answer
from backend.drafting_engine import source_packet
from backend.grounding import material_values_supported
from backend.models.review_llm import LocalReviewLLM, verification_schema
from backend.research_schema import Checks

BASELINE_PROMPT = '''You are a legal research assistant. Answer the question using the numbered sources below.
Write concise factual claims. After each claim list the ids of the sources that support it (e.g. S1, S3).
Do not use information that is not in the sources. If the sources do not answer the question, return an empty claims list.'''


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class BaselineClaim(_Strict):
    text: str = Field(min_length=1, max_length=1800)
    source_ids: list[str] = Field(max_length=8)


class BaselineAnswer(_Strict):
    claims: list[BaselineClaim] = Field(max_length=16)


def llm_for_role(role):
    """Plug-and-play client per role; uses LocalReviewLLM.for_role when available."""
    if hasattr(LocalReviewLLM, 'for_role'):
        return LocalReviewLLM.for_role(role)
    base = LocalReviewLLM.from_env()
    def env(key, fallback): return os.getenv(f'LEXIMIND_{role.upper()}_{key}', fallback)
    return replace(base, provider=env('LLM_PROVIDER', base.provider), base_url=env('BASE_URL', base.base_url),
                   model=env('LLM_MODEL', base.model), api_key=env('API_KEY', base.api_key))


def model_name(llm):
    return getattr(llm, 'model', None) or type(llm).__name__


def packet_context(packet):
    """Deduplicate document metadata without removing source text or evidence IDs."""
    documents, sources, keys = {}, [], {}
    for p in packet:
        metadata = {k: v for k, v in p.items() if k not in {'source_id', 'text'}}
        key = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
        if key not in keys:
            doc_id = f'D{len(keys) + 1}'
            keys[key] = doc_id
            documents[doc_id] = metadata
        sources.append({'source_id': p['source_id'], 'text': p['text'], 'document_id': keys[key]})
    return {'sources': sources, 'documents': documents}


def run_baseline(question, documents, chunks, llm):
    """Single-pass RAG: the same retrieved chunks, shown whole as [S1]..[Sn]."""
    labels = {f'S{i}': c for i, c in enumerate(chunks, 1)}
    names = {d['id']: d['name'] for d in documents}
    if not labels:
        return {'claims': [], 'notes': {'abstained': 'no retrieved sources'}}
    sources = [{'source_id': k, 'document': names.get(c['document_id']), 'page': c.get('page'), 'text': c['text']} for k, c in labels.items()]
    raw = llm.complete([{'role': 'system', 'content': BASELINE_PROMPT},
                        {'role': 'user', 'content': json.dumps({'question': question, 'sources': sources}, ensure_ascii=False)}],
                       BaselineAnswer.model_json_schema())
    answer = BaselineAnswer.model_validate(raw)
    claims = [{'text': c.text, 'citations': [{'source_id': r, 'quote': labels[r]['text'] if r in labels else '',
                                              'chunk_id': labels[r]['id'] if r in labels else None} for r in dict.fromkeys(c.source_ids)]}
              for c in answer.claims]
    return {'claims': claims}


def run_system(question, documents, chunks, gen_llm, verify_llm, retriever=None, verify=True, numeric_guard=True, authority_filter=True):
    """Pure-function replica of backend/chat.py execute(): line-level packet, generation, CHECK pass,
    numeric guard and authority-type filter. `chunks` are already retrieved unless `retriever` is given."""
    if retriever is not None:
        chunks = retriever(chunks, question, 10)
    catalog, packet = source_packet(documents, chunks)
    notes = {'proposed': 0, 'rejected': []}
    if not packet:
        return {'claims': [], 'notes': notes}
    context = {'question': question, 'history': [], **packet_context(packet)}
    proposed = Answer.model_validate(gen_llm.complete([{'role': 'system', 'content': SYSTEM},
                                                       {'role': 'user', 'content': json.dumps(context, ensure_ascii=False, separators=(',', ':'))}], Answer.model_json_schema()))
    items = [{'id': str(uuid4()), **p.model_dump()} for p in proposed.propositions]
    for item in items:
        if item['kind'] == 'fact':
            item['text'] = 'According to the selected source: ' + item['text']
    notes['proposed'] = len(items)
    decisions = {}
    if items and verify:
        checks = Checks.model_validate(verify_llm.complete(
            [{'role': 'system', 'content': CHECK}, {'role': 'user', 'content': json.dumps({'items': items, **packet_context(packet)}, ensure_ascii=False, separators=(',', ':'))}],
            verification_schema(Checks, items)))
        decisions = {str(d.id): d.supported for d in checks.decisions}
        if len(decisions) != len(checks.decisions) or set(decisions) != {i['id'] for i in items}:
            raise ValueError('Incomplete verification')
    docs = {d['id']: d for d in documents}
    claims = []
    for item in items:
        refs = list(dict.fromkeys(item['source_ids']))
        valid_refs = all(r in catalog for r in refs)
        quotes = [catalog[r]['quote'] for r in refs if r in catalog]
        types = {docs[catalog[r]['chunk']['document_id']]['metadata'].get('document_type') for r in refs if r in catalog}
        checks = {'verifier': decisions.get(item['id'], True) if verify else True, 'source_ids_valid': valid_refs,
                  'numeric': material_values_supported(item['text'], quotes) if numeric_guard else True,
                  'authority': item['kind'] != 'legal' or bool(types & {'statute', 'judgment'}) if authority_filter else True}
        if not all(checks.values()):
            notes['rejected'].append({'text': item['text'], 'failed': [k for k, v in checks.items() if not v]})
            continue
        claims.append({'text': item['text'], 'kind': item['kind'],
                       'citations': [{'source_id': r, 'quote': catalog[r]['quote'] if r in catalog else '',
                                      'chunk_id': catalog[r]['chunk']['id'] if r in catalog else None} for r in refs]})
    return {'claims': claims, 'notes': notes}


SYSTEM_FLAGS = {
    'system': {},
    'system_no_verify': {'verify': False},
    'system_no_numeric': {'numeric_guard': False},
    'system_no_authority': {'authority_filter': False},
    'system_generation_only': {'verify': False, 'numeric_guard': False, 'authority_filter': False},
}
ARMS = ['baseline', *SYSTEM_FLAGS]


def parse_arm(spec):
    """'system_no_verify@bm25' -> ('system_no_verify', 'bm25'); retriever defaults to None (runner default)."""
    name, _, retriever = spec.partition('@')
    if name not in ARMS:
        raise KeyError(f'Unknown arm {name!r}; choose from {ARMS}')
    return name, retriever or None


def run_arm(name, query, chunks, llms):
    """Dispatch with uniform timing; chunks are the retrieved, budgeted context."""
    started = time.monotonic()
    if name == 'baseline':
        out = run_baseline(query['question'], query['documents'], chunks, llms['baseline'])
    else:
        out = run_system(query['question'], query['documents'], chunks, llms['chat'], llms.get('verifier') or llms['chat'], **SYSTEM_FLAGS[name])
    out['latency_s'] = round(time.monotonic() - started, 3)
    return out
