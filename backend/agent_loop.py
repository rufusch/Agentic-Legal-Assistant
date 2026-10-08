"""Bounded agentic retrieve -> generate -> verify -> re-retrieve loop, verifier selection and computed confidence.

Every round's proposals pass the caller's full fail-closed check; the loop only decides what to retry and
which extra evidence to add. Source ids come from one merged catalog, so ids never collide across rounds.
"""
import os
import re
from backend.llm_review_engine import source_catalog
from backend.models.review_llm import ReviewCancelled
from backend.retrieval import search
from backend.review_engine import confidence

RETRY = ('Statements in previously_rejected failed source verification for the reasons given. Do not repeat them '
    'unless the new excerpts explicitly support them. Propose only statements that fill the unanswered gap, using '
    'the supplied excerpts and their exact source_ids. Abstain with an empty list if the gap is still unsupported.')
STOP = {'the','a','an','of','to','in','on','for','and','or','is','are','was','were','be','by','with','that','this','it',
    'as','at','from','its','their','any','not','no','under','which','who','whom','what','when','does','do','has','have',
    'according','selected','source','supplied','says','said','shall','may','will','can','into','than','then','such'}


def words(text): return [w for w in re.findall(r'[a-z0-9]+', str(text).lower()) if w not in STOP and len(w) > 2]


def max_rounds():
    try: return max(1, min(4, int(os.getenv('LEXIMIND_AGENT_MAX_ROUNDS', '2'))))
    except ValueError: return 2


def identity(m):
    meta = getattr(m, 'metadata', None) or {}
    return (getattr(m, 'provider', None), getattr(m, 'base_url', None), getattr(m, 'model', None) or meta.get('version'))


def is_independent(llm, verify_llm): return verify_llm is not llm and identity(verify_llm) != identity(llm)


def verifier(llm, injected=None):
    """A separately configured verifier (LEXIMIND_VERIFIER_*) or the workflow's own model (correlated errors)."""
    if injected is not None: return injected
    if any(k.startswith('LEXIMIND_VERIFIER_') and v for k, v in os.environ.items()):
        from backend.models.review_llm import LocalReviewLLM
        return LocalReviewLLM.for_role('verifier')
    return llm


def verification_info(llm, verify_llm):
    ind = is_independent(llm, verify_llm)
    return {'same_model': not ind, 'independent_verifier': ind, 'generator_model': identity(llm)[2],
        'verifier_model': identity(verify_llm)[2], 'verifier_provider': identity(verify_llm)[0]}


def claim_status(independent, has_span): return 'supported' if independent and has_span else 'partially_supported'


def claim_confidence(refs, catalog, docs, *, independent, first_round=True, authority_ok=None):
    """Score a verifier-accepted claim from inspectable signals; returns (score, explanation)."""
    chunks = [catalog[r]['chunk'] for r in refs if r in catalog]
    doc_ids = {c['document_id'] for c in chunks}
    score = .5; why = ['verifier accepted']
    if independent: score += .25; why.append('independent verifier model (+)')
    else: why.append('same-model verifier, correlated errors possible')
    if len(doc_ids) > 1: score += .1; why.append(f'{len(doc_ids)} independent documents (+)')
    elif len(chunks) > 1: score += .05; why.append('multiple passages (+)')
    if first_round: score += .05
    else: score -= .05; why.append('recovered on a retry round (-)')
    if any(c.get('ocr') or docs.get(c['document_id'], {}).get('ocr_used') for c in chunks): score -= .15; why.append('OCR source (-)')
    if any(docs.get(d, {}).get('metadata', {}).get('document_type') == 'user_input' for d in doc_ids) or any(re.search(r'\balleg', catalog[r]['quote'], re.I) for r in refs if r in catalog):
        score -= .15; why.append('user-provided or allegation source (-)')
    if authority_ok is True: score += .05; why.append('authority type matches (+)')
    elif authority_ok is False: score -= .2; why.append('authority type mismatch (-)')
    return round(min(.95, max(.05, score)), 3), '; '.join(why)


def overall(claims, independent, retried=0):
    """Source-weighted mean of published claim confidences."""
    if not claims: return confidence(0, 'No verified propositions.')
    weights = [max(1, len(c.get('citation_ids', []))) for c in claims]
    score = round(sum(c['confidence'] * w for c, w in zip(claims, weights)) / sum(weights), 3)
    return confidence(score, f'Source-weighted mean of {len(claims)} verified claims; ' + ('independent verifier model' if independent else 'same-model verifier, correlated errors possible') + (f'; {retried} recovered by agentic retry' if retried else '') + '. Not a guarantee of legal correctness.')


def entry(key, ref, docs):
    doc = docs[ref['chunk']['document_id']]; kind = doc['metadata'].get('document_type', 'other')
    return {'source_id': key, 'text': ref['quote'], 'document_name': doc['name'], 'document_type': kind,
        'jurisdiction': doc['metadata'].get('jurisdiction'), 'user_provided': kind == 'user_input'}


def extend_catalog(catalog, chunks):
    """Append new chunk lines under fresh, never-reused source ids."""
    have = {r['chunk']['id'] for r in catalog.values()}
    n = max([int(k[1:]) for k in catalog] or [0]); added = []
    for ref in source_catalog([c for c in chunks if c['id'] not in have]).values():
        n += 1; catalog[f'E{n}'] = ref; added.append(f'E{n}')
    return added


def duplicate(item, accepted):
    if item.get('conflict_id'): return False  # two sides of one conflict are deliberately similar
    a = set(words(item['text'])); section = item.get('section', item.get('kind'))
    for other in accepted:
        o = other['item']
        if o.get('section', o.get('kind')) != section: continue
        b = set(words(o['text']))
        if a == b or (a and b and len(a & b) / len(a | b) >= .85): return True
    return False


def refine_query(question, rejected):
    """Original question plus salient terms from rejected statements and verifier reasons."""
    terms = list(dict.fromkeys(w for x in rejected for w in words(x['text'] + ' ' + x.get('reason', ''))))[:40]
    return (question + ' ' + ' '.join(terms)).strip()


def run(*, question, documents, chunks, pool, budget, propose, check, cancelled=lambda: False, progress=lambda *a: None, rounds=None, limit=10, stages=('generating', 'verifying')):
    """propose(packet, feedback, round) -> (items, messages); check(items, packet, catalog) -> {id: {'supported','reason',...}}.
    Items carry 'id', 'text', 'source_ids'. Only checked items are ever returned as accepted."""
    rounds = rounds or max_rounds(); docs = {d['id']: d for d in documents}
    catalog = {}; used = {c['id']: c for c in chunks}; keys = extend_catalog(catalog, chunks)
    accepted, rejected_all, trace = [], [], []; messages = None; feedback = None; query = question; added = [c['id'] for c in chunks]; last = []
    for r in range(1, rounds + 1):
        if cancelled(): raise ReviewCancelled()
        if r > 1:
            query = refine_query(question, last)
            fresh = [c for c in search(pool, query, limit) if c['id'] not in used]
            cited = list(dict.fromkeys(catalog[s]['chunk']['id'] for x in last for s in x.get('source_ids', []) if s in catalog))
            selected = []; size = 0
            for c in fresh + [used[i] for i in cited]:  # newly found evidence first, then the rejected claims' own context
                if size + len(c['text']) <= budget: selected.append(c); size += len(c['text'])
            fresh = [c for c in fresh if c in selected]
            if not fresh:
                trace.append({'round': r, 'query': query, 'added_chunk_ids': [], 'proposed': 0, 'accepted': 0, 'rejected': 0, 'stopped': 'no_new_evidence'}); break
            used.update({c['id']: c for c in fresh}); extend_catalog(catalog, fresh)
            ids = {c['id'] for c in selected}; keys = [k for k, v in catalog.items() if v['chunk']['id'] in ids]; added = [c['id'] for c in fresh]
            feedback = {'previously_rejected': [{'text': x['text'], 'reason': x.get('reason', '')} for x in last], 'instruction': RETRY,
                'already_verified': [a['item']['text'] for a in accepted]}
        packet = [entry(k, catalog[k], docs) for k in keys]
        if not packet: break
        progress(stages[0], .35 if r == 1 else .55, 'Reading source excerpts' if r == 1 else f'Agentic retry {r}: re-reading new evidence for rejected statements')
        items, sent = propose(packet, feedback, r)
        messages = messages or sent
        if items: progress(stages[1], .7 if r == 1 else .8, 'Checking every proposed statement against its sources')
        verdicts = check(items, packet, catalog) if items else {}
        acc, rej = [], []
        for item in items:
            v = verdicts[item['id']]
            if not v['supported']: rej.append({**item, 'reason': v.get('reason', '')})
            elif not duplicate(item, accepted + acc): acc.append({'item': item, 'verdict': v, 'round': r})
        accepted += acc; rejected_all += rej; last = rej
        trace.append({'round': r, 'query': query, 'added_chunk_ids': added, 'packet_sources': len(packet), 'proposed': len(items), 'accepted': len(acc), 'rejected': len(rej)})
        if accepted and not rej: break
    return {'accepted': accepted, 'rejected': rejected_all, 'catalog': catalog, 'chunks': list(used.values()), 'trace': trace, 'messages': messages}
