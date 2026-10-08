import json
import pytest
from fastapi.testclient import TestClient
from backend import agent_loop as agent
from backend.app import create_app
from backend.chat import retrieval_query, is_followup, summarize
from backend.drafting_requirements import prefill, requirements
from backend.evidence import EvidenceBundle
from backend.models.review_llm import ReviewCancelled
from tests.test_common import upload, finish
from tests.test_research import wait

DOC = {'id':'d1','name':'a.txt','metadata':{'document_type':'case'}}
DOC2 = {'id':'d2','name':'b.txt','metadata':{'document_type':'case'}}
C1 = {'id':'c1','document_id':'d1','text':'Payment is due on 15 October.','start_offset':0}
C2 = {'id':'c2','document_id':'d2','text':'Termination requires thirty days written notice.','start_offset':0}


def harness(round_items, verdict, pool=(C1, C2), monkeypatch=None, hits=None, **kw):
    """propose returns round_items[r](packet); check accepts per verdict(item, packet)."""
    if monkeypatch: monkeypatch.setattr(agent, 'search', lambda chunks, q, limit: list(hits if hits is not None else chunks))
    calls = []
    def propose(packet, feedback, rnd):
        calls.append({'round':rnd,'feedback':feedback,'packet':packet})
        return [{'id':f'{rnd}-{i}', **x} for i, x in enumerate(round_items[rnd](packet))], [{'role':'user','content':'x'}]
    def check(items, packet, catalog):
        keys = {p['source_id'] for p in packet}
        return {i['id']:{'supported':verdict(i, packet) and all(s in keys for s in i['source_ids']),'reason':'no support'} for i in items}
    out = agent.run(question='When is payment due and termination notice?', documents=[DOC, DOC2], chunks=[C1], pool=list(pool), budget=10000, propose=propose, check=check, **kw)
    return out, calls


def sid(packet, word): return next(p['source_id'] for p in packet if word in p['text'])


def test_retry_recovers_with_new_chunk_and_merges_catalog(monkeypatch):
    rounds = {1: lambda p: [{'text':'Payment is due on 15 October.','source_ids':[sid(p,'Payment')]}, {'text':'Termination needs thirty days notice.','source_ids':[sid(p,'Payment')]}],
              2: lambda p: [{'text':'Termination needs thirty days notice.','source_ids':[sid(p,'Termination')]}, {'text':'Payment is due on 15 October.','source_ids':[sid(p,'Payment')]}]}
    out, calls = harness(rounds, lambda i, p: any(w in next(x['text'] for x in p if x['source_id']==i['source_ids'][0]) for w in i['text'].split()[:1]), monkeypatch=monkeypatch)
    assert [t['round'] for t in out['trace']] == [1, 2] and out['trace'][1]['added_chunk_ids'] == ['c2']
    assert out['trace'][0]['rejected'] == 1 and out['trace'][1]['accepted'] == 1  # duplicate payment claim merged away
    texts = [a['item']['text'] for a in out['accepted']]
    assert sorted(texts) == ['Payment is due on 15 October.', 'Termination needs thirty days notice.']
    fb = calls[1]['feedback']; assert fb['previously_rejected'][0]['reason'] == 'no support' and 'Do not repeat' in fb['instruction']
    # Round-1 id E1 still means the payment line in round 2; the new chunk got a fresh id.
    assert sid(calls[0]['packet'], 'Payment') == sid(calls[1]['packet'], 'Payment') == 'E1' and sid(calls[1]['packet'], 'Termination') == 'E2'
    assert len(out['catalog']) == len(set(out['catalog'])) and {c['id'] for c in out['chunks']} == {'c1', 'c2'}


def test_rejected_never_published_and_loop_stops_at_max_rounds(monkeypatch):
    monkeypatch.setenv('LEXIMIND_AGENT_MAX_ROUNDS', '2')
    c3 = {'id':'c3','document_id':'d2','text':'Unrelated clause about arbitration.','start_offset':0}
    bad = lambda p: [{'text':'Invented fabricated fact.','source_ids':[p[-1]['source_id']]}]
    out, calls = harness({1:bad, 2:bad, 3:bad}, lambda i, p: False, pool=(C1, C2, c3), monkeypatch=monkeypatch)
    assert len(calls) == 2 and len(out['trace']) == 2 and not out['accepted'] and len(out['rejected']) == 2


def test_stops_without_new_evidence_and_respects_cancellation(monkeypatch):
    rounds = {1: lambda p: [{'text':'Nothing.','source_ids':['E1']}]}
    out, calls = harness(rounds, lambda i, p: False, pool=(C1,), monkeypatch=monkeypatch)
    assert len(calls) == 1 and out['trace'][-1]['stopped'] == 'no_new_evidence'
    with pytest.raises(ReviewCancelled): harness(rounds, lambda i, p: False, monkeypatch=monkeypatch, cancelled=lambda: True)


def test_unknown_source_ids_rejected_and_ids_never_collide(monkeypatch):
    rounds = {1: lambda p: [{'text':'Claim citing a future id.','source_ids':['E2']}], 2: lambda p: [{'text':'Claim citing a future id.','source_ids':['E2']}]}
    out, _ = harness(rounds, lambda i, p: True, monkeypatch=monkeypatch)
    # E2 did not exist in round 1 so it was rejected there; it is valid only once the round-2 packet contains it.
    assert out['trace'][0]['rejected'] == 1 and out['trace'][1]['accepted'] == 1
    assert out['catalog']['E2']['chunk']['id'] == 'c2' and out['catalog']['E1']['chunk']['id'] == 'c1'


def test_confidence_and_supported_semantics():
    cat = {'E1':{'chunk':C1,'quote':C1['text']}, 'E2':{'chunk':C2,'quote':C2['text']}}
    docs = {'d1':DOC, 'd2':DOC2}
    same, why_same = agent.claim_confidence(['E1'], cat, docs, independent=False)
    ind, why = agent.claim_confidence(['E1','E2'], cat, docs, independent=True)
    retry, _ = agent.claim_confidence(['E1'], cat, docs, independent=False, first_round=False)
    ocr, _ = agent.claim_confidence(['E1'], {'E1':{'chunk':{**C1,'ocr':True},'quote':C1['text']}}, docs, independent=False)
    assert 0 <= retry < same < ind <= 1 and ocr < same and 'independent verifier' in why and 'same-model' in why_same
    assert agent.claim_status(True, True) == 'supported' and agent.claim_status(False, True) == agent.claim_status(True, False) == 'partially_supported'
    o = agent.overall([{'confidence':.9,'citation_ids':[1,2]}, {'confidence':.3,'citation_ids':[1]}], True)
    assert o['score'] == .7 and o['level'] == 'medium'
    assert agent.overall([], True)['level'] == 'unavailable'


class Gen:
    metadata = {'version':'gen-model','kind':'local_llm','trainable':True}
    model = 'gen-model'
    def status(self): return {'ready':True}
    def complete(self, messages, schema, cancelled=lambda:False):
        p = json.loads(messages[-1]['content']); s = p['sources']
        if 'conflicts' in schema.get('properties', {}):
            st = [x for x in s if x['document_type']=='statute']
            a = next(x['source_id'] for x in st if 'shall provide' in x['text']); b = next(x['source_id'] for x in st if 'need not' in x['text'])
            if getattr(self, 'same_doc', False): b = a
            return {'propositions':[{'section':'legal_framework','text':'The first statute provides a hearing.','source_ids':[a]}],
                'conflicts':[{'topic':'Hearing requirement','side_a':{'text':'One statute requires a hearing.','source_ids':[a]},'side_b':{'text':'Another statute says a hearing need not be given.','source_ids':[b]},'explanation':'The supplied statutes differ on whether a hearing is required.'}],'limitations':[]}
        return {'propositions':[{'text':'Payment is due on 15 October.','kind':'fact','source_ids':[s[0]['source_id']]}]}


class Verifier:
    metadata = {'version':'verifier-model','kind':'hosted_llm'}
    model = 'verifier-model'
    def __init__(self, reject=()): self.calls = 0; self.reject = reject
    def status(self): return {'ready':True}
    def complete(self, messages, schema, cancelled=lambda:False):
        self.calls += 1
        return {'decisions':[{'id':i['id'],'supported':not any(r in i['text'] for r in self.reject),'reason':'checked'} for i in json.loads(messages[-1]['content'])['items']]}


def test_chat_independent_verifier_marks_supported_and_records_summary(tmp_path):
    gen, ver = Gen(), Verifier()
    app = create_app(tmp_path, {'a':'tenant-a'}, review_engine='extractive', chat_llm=gen, verify_llm=ver)
    with TestClient(app) as c:
        c.headers['Authorization'] = 'Bearer a'; t, _ = upload(c); finish(c, t); rid = t['document_id']
        cid = c.post('/api/v1/conversations', json={'document_ids':[rid]}).json()['data']['conversation_id']
        ticket = c.post(f'/api/v1/conversations/{cid}/messages', json={'content':'When is payment due?','selected_document_ids':[rid]}).json()['data']
        assert wait(c, ticket['job_id'])['status'] == 'completed_with_warnings'
        msg = next(m for m in c.get(f'/api/v1/conversations/{cid}/messages').json()['data'] if m['id']==ticket['assistant_message_id'])
        assert ver.calls == 1 and msg['verification']['same_model'] is False and msg['verification']['verifier_model'] == 'verifier-model'
        assert msg['claims'][0]['verification_status'] == 'supported' and msg['confidence']['score'] >= .75 and msg['agent_trace'][0]['accepted'] == 1
        EvidenceBundle.model_validate(msg)
        convo = c.get('/api/v1/conversations').json()['data']['items'][0]
        assert convo['conversation_summary']['recent_questions'] == ['When is payment due?'] and 'NOT evidence' in convo['conversation_summary']['note']
    app.state.store.close()


def authority(c, text, key):
    t, _ = upload(c, text, key); finish(c, t); store = c.app.state.store
    with store.transaction():
        d = store.get('tenant-a','document',t['document_id']); d['metadata'] = {'document_type':'statute','jurisdiction':'IN'}; store.save('tenant-a','document',d)
    return t['document_id']


@pytest.mark.parametrize('case', ['published', 'same_doc', 'side_rejected'])
def test_research_conflict_requires_two_verified_sides_from_different_documents(tmp_path, case):
    gen = Gen(); gen.same_doc = case == 'same_doc'
    ver = Verifier(reject=('need not',) if case == 'side_rejected' else ())
    app = create_app(tmp_path, {'a':'tenant-a'}, review_engine='extractive', research_llm=gen, verify_llm=ver)
    with TestClient(app) as c:
        c.headers['Authorization'] = 'Bearer a'
        authority(c, b'Statute A: the authority shall provide an opportunity of hearing.\n', 'u1')
        authority(c, b'Statute B: a hearing need not be given in urgent cases.\n', 'u2')
        r = c.post('/api/v1/research', json={'question':'Is a hearing required before the order?'}).json()['data']
        assert wait(c, r['job_id'])['status'] == 'completed_with_warnings'
        memo = c.get('/api/v1/research/'+r['research_id']).json()['data']
    app.state.store.close()
    assert memo['verification']['same_model'] is False and memo['claims']
    conflicts = memo['conflicting_authorities']
    if case == 'published':
        assert len(conflicts) == 1 and conflicts[0]['issue'] == 'Hearing requirement'
        groups = conflicts[0]['authority_groups']; cites = {c['id']:c for c in memo['citations']}
        assert len(groups) == 2 and len({cites[g['citation_ids'][0]]['document_id'] for g in groups}) == 2
        assert all(any(cl['id'] in g['claim_ids'] for cl in memo['claims']) for g in groups)
    else:
        assert conflicts == [] and not any('need not' in cl['text'] or 'requires a hearing' in cl['text'] for cl in memo['claims'])


def test_followup_query_uses_previous_question_and_claim_terms():
    history = [{'role':'user','content':'When is payment due under the supply contract?','created_at':'1','status':'completed'},
        {'role':'assistant','content':'x','created_at':'2','status':'completed','claims':[{'text':'According to the selected source: Payment is due on 15 October to the vendor.'}],'citations':[{'document_name':'contract.txt'}]}]
    q, follow = retrieval_query('And what about termination?', history)
    assert follow and 'supply contract' in q and 'october' in q and 'vendor' in q and 'According' not in q
    assert retrieval_query('Explain the arbitration seat and governing law provisions in detail please', history) == ('Explain the arbitration seat and governing law provisions in detail please', False)
    assert not is_followup('What about it?', [])
    s = summarize(history); assert s['top_cited_documents'] == ['contract.txt'] and 'payment' in s['key_terms']


def test_prefill_only_with_exact_quotes():
    text = 'IN THE COURT OF SESSIONS AT PUNE\nApplicant: Ramesh Kumar Sharma, aged 34\nFIR No. 123/2024 registered at Shivajinagar.\nHe was arrested on 12 March 2024.\n'
    chunk = {'id':'k1','document_id':'d1','text':text,'start_offset':100,'source_part':1}
    draft = {'document_type':'bail_application','jurisdiction':'IN-MH','instructions':'Draft bail.','court':None,'facts':{}}
    draft['requirements'] = requirements(draft)
    prefill(draft, [{'id':'d1','name':'fir.txt','metadata':{'document_type':'case'}}], [chunk])
    got = {r['key']:r for r in draft['requirements']}
    assert got['applicant_name']['current_answer'] == 'Ramesh Kumar Sharma' and got['applicant_name']['source'] == 'document'
    assert got['case_number']['current_answer'] == 'FIR No. 123/2024' and got['court']['current_answer'] == 'COURT OF SESSIONS AT PUNE'
    assert got['arrest_status']['current_answer'] == 'arrested on 12 March 2024'
    for r in got.values():
        if r.get('source') == 'document':
            cit = r['citation']; assert text[cit['start_offset']-100:cit['end_offset']-100] == cit['quote'] and r['current_answer'].split(' and ')[0] in cit['quote']
    assert got['relief']['current_answer'] is None and got['relief']['found_in_source'] is False
    assert draft['facts']['applicant_name'] == 'Ramesh Kumar Sharma' and draft['court'] == 'COURT OF SESSIONS AT PUNE'
    # Authorities and user intake are never mined for case facts; user answers are never overwritten.
    d2 = {**draft, 'facts':{'applicant_name':'User Name'}, 'court':None}; d2['requirements'] = requirements(d2)
    prefill(d2, [{'id':'d1','name':'s.txt','metadata':{'document_type':'statute'}}], [chunk])
    assert {r['key']:r for r in d2['requirements']}['applicant_name']['current_answer'] == 'User Name' and not any(r.get('source')=='document' for r in d2['requirements'])
