import json
from pathlib import Path

import pytest

from backend.chat import CHECK, SYSTEM
from evaluation.harness import retrievers
from evaluation.harness.arms import BASELINE_PROMPT
from evaluation.harness.dataset import load
from evaluation.harness.judge import JUDGE_PROMPT, Judge, deterministic_flags
from evaluation.harness.metrics import arm_metrics, summarize
from evaluation.harness.runner import judge_warnings, run
from scripts.run_eval import main

ROOT = Path(__file__).resolve().parents[1]
FEE = 'The service fee is INR 5000 payable within ten days of invoice.'
FILLER = 'The parties agree that notices shall be delivered in writing to the registered office.'


def write_dataset(tmp_path):
    sources = [{'id': 'contract', 'text': FEE + '\n' + FILLER, 'metadata': {'document_type': 'contract'}},
               {'id': 'other', 'text': 'Unrelated memorandum about office furniture and parking.'}]
    rows = [{'id': 'fee', 'split': 'dev', 'question': 'What is the service fee?', 'sources': sources,
             'gold': [{'doc': 'contract', 'quote': 'INR 5000 payable'}], 'answerable': True},
            {'id': 'fee-h', 'split': 'heldout', 'question': 'When is the service fee payable?', 'sources': sources,
             'gold': [{'doc': 'contract', 'quote': 'within ten days'}], 'answerable': True},
            {'id': 'none', 'split': 'dev', 'question': 'Who is the arbitrator?', 'sources': sources, 'answerable': False}]
    path = tmp_path / 'data.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    return path


class FakeLLM:
    """Dispatches on the system prompt. mode: 'correct' | 'fabricate'. Abstains on the arbitrator question."""

    def __init__(self, mode='correct', model='fake-gen'):
        self.mode, self.model, self.calls = mode, model, 0

    def status(self): return {'ready': True}

    def complete(self, messages, schema, cancelled=None):
        self.calls += 1
        system, payload = messages[0]['content'], json.loads(messages[1]['content'])
        claim = 'The service fee is INR 5000.' if self.mode == 'correct' else 'Under Section 420 the service fee is INR 5000.'
        if system == JUDGE_PROMPT:
            return {'judgments': [{'id': c['id'], 'label': 'supported', 'reason': 'entailed'} for c in payload['claims']]}
        if system == CHECK:
            return {'decisions': [{'id': i['id'], 'supported': True, 'reason': 'ok'} for i in payload['items']]}
        abstain = 'arbitrator' in payload['question']
        ref = next(s['source_id'] for s in payload['sources'] if 'INR 5000' in s['text'])
        if system == SYSTEM:
            return {'propositions': [] if abstain else [{'text': claim, 'kind': 'fact', 'source_ids': [ref]}]}
        if system == BASELINE_PROMPT:
            return {'claims': [] if abstain else [{'text': claim, 'source_ids': [ref]}]}
        raise AssertionError('unexpected prompt')


def test_loader_maps_gold_quotes_to_chunks_and_rejects_missing_quotes(tmp_path):
    queries = load(write_dataset(tmp_path))
    assert [q['id'] for q in queries] == ['fee', 'fee-h', 'none']
    assert queries[0]['gold_chunk_ids'] == ['contract:p1:0'] and queries[2]['gold_chunk_ids'] == []
    assert [q['id'] for q in load(write_dataset(tmp_path), split='heldout')] == ['fee-h']
    bad = tmp_path / 'bad.jsonl'
    bad.write_text(json.dumps({'id': 'x', 'question': 'q', 'sources': [{'id': 's', 'text': 'abc'}], 'gold': [{'doc': 's', 'quote': 'zzz'}]}))
    with pytest.raises(ValueError, match='not found verbatim'):
        load(bad)


def test_public_dataset_gold_quotes_resolve():
    queries = load(ROOT / 'evaluation/datasets/public_dev.jsonl')
    assert len(queries) >= 12 and sum(not q['answerable'] for q in queries) >= 3
    assert {q['split'] for q in queries} == {'dev', 'heldout'}
    assert all(q['gold_chunk_ids'] for q in queries if q['answerable'])


def test_deterministic_fabrication_detector():
    corpus = 'Section 73 bars remote loss. Bharat Chaudhary v. State of Bihar (2003) 8 SCC 77. Fee INR 5000.'
    ok = {'text': 'Section 73 bars remote loss.', 'citations': [{'source_id': 'E1'}]}
    assert deterministic_flags(ok, {'E1'}, corpus) == []
    assert deterministic_flags({**ok, 'citations': [{'source_id': 'E9'}]}, {'E1'}, corpus) == ["cites unknown source 'E9'"]
    assert any('section 74' in f for f in deterministic_flags({**ok, 'text': 'Section 74 applies.'}, {'E1'}, corpus))
    assert any('Gurbaksh' in f for f in deterministic_flags({**ok, 'text': 'See Gurbaksh Singh v. State of Punjab.'}, {'E1'}, corpus))
    assert deterministic_flags({**ok, 'text': 'Bharat Chaudhary v. State of Bihar (2003) 8 SCC 77 applies.'}, {'E1'}, corpus) == []
    assert any('2010' in f for f in deterministic_flags({**ok, 'text': 'Held in (2010) 1 SCC 684.'}, {'E1'}, corpus))


def test_metric_math_and_refusal_on_mismatched_query_sets():
    q = {'id': 'a', 'split': 'dev', 'answerable': True}
    rows = [{'query': q, 'prediction': {'claims': [1, 2, 3, 4], 'latency_s': 2.0},
             'judgments': [{'label': l} for l in ['supported', 'partially_supported', 'unsupported', 'fabricated']]},
            {'query': {'id': 'b', 'split': 'dev', 'answerable': False}, 'prediction': {'claims': [], 'latency_s': 1.0}, 'judgments': []}]
    m = arm_metrics(rows)
    assert m['groundedness'] == .375 and m['strict_groundedness'] == .25 and m['fabricated_claims'] == 1
    assert m['fabrication_rate'] == .25 and m['answer_coverage'] == 1 and m['correct_abstention'] == 1 and m['mean_latency_s'] == 1.5
    with pytest.raises(ValueError, match='different query sets'):
        summarize({'baseline': rows, 'system': rows[:1]})


def test_ranking_metrics():
    m = retrievers.ranking_metrics(['x', 'g1', 'y', 'g2'], ['g1', 'g2'], 3)
    assert m['recall@3'] == .5 and m['mrr'] == .5 and 0 < m['ndcg@3'] < 1


def test_runner_end_to_end_with_fake_llms(tmp_path):
    queries = load(write_dataset(tmp_path))
    honest, liar, judge = FakeLLM('correct'), FakeLLM('fabricate'), FakeLLM(model='fake-judge')
    preds, judgments, metrics = run(queries, ['baseline', 'system', 'system_no_numeric'], {'baseline': liar, 'chat': honest, 'verifier': honest, 'judge': judge}, cache_dir=tmp_path / 'cache')
    assert metrics['baseline']['all']['fabricated_claims'] == 2 and metrics['baseline']['all']['groundedness'] == 0
    assert metrics['system']['all']['fabricated_claims'] == 0 and metrics['system']['all']['groundedness'] == 1
    assert metrics['system']['all']['correct_abstention'] == 1 and metrics['system']['heldout']['queries'] == 1
    assert all(p['context_recall'] == 1 for p in preds if p['id'] != 'none')
    # The numeric guard is what stops a fabricating generator in the system arm.
    _, _, guarded = run(queries, ['system', 'system_no_numeric'], {'chat': liar, 'verifier': liar, 'judge': judge})
    assert guarded['system']['all']['fabricated_claims'] == 0 and guarded['system_no_numeric']['all']['fabricated_claims'] == 2
    # Judge results are cached on disk; a rerun makes no judge calls.
    calls = judge.calls
    run(queries, ['system'], {'chat': honest, 'verifier': honest, 'judge': judge}, cache_dir=tmp_path / 'cache')
    assert judge.calls == calls


def test_model_errors_are_recorded_and_same_model_judge_warns(tmp_path):
    class Broken(FakeLLM):
        def complete(self, *a, **k): raise RuntimeError('model down')
    queries = load(write_dataset(tmp_path))
    preds, _, metrics = run(queries, ['baseline'], {'baseline': Broken(), 'judge': FakeLLM(model='j')})
    # 'none' retrieves nothing, so no model call is made and it abstains; the others record the failure.
    assert [p.get('error', '')[:12] for p in preds] == ['RuntimeError', 'RuntimeError', '']
    assert metrics['baseline']['all']['failures'] == 2 and metrics['baseline']['all']['answer_coverage'] == 0
    assert judge_warnings({'chat': FakeLLM(model='m'), 'judge': FakeLLM(model='m')})
    assert not judge_warnings({'chat': FakeLLM(model='m'), 'judge': FakeLLM(model='n')})


def test_retrieval_only_cli_on_public_dataset(tmp_path):
    table = main(['--dataset', str(ROOT / 'evaluation/datasets/public_dev.jsonl'), '--retrieval-only', '--retrievers', 'hybrid,bm25_plain', '--out', str(tmp_path / 'r')])
    assert table['hybrid']['all']['recall@10'] > 0 and table['hybrid']['all']['queries'] >= 9
    assert 'heldout' in table['bm25_plain']
    assert '| hybrid |' in (tmp_path / 'r/results.md').read_text()


def test_full_cli_with_injected_fake_models(tmp_path, monkeypatch):
    import scripts.run_eval as cli
    monkeypatch.setattr(cli, 'build_llms', lambda arms: {'baseline': FakeLLM(), 'chat': FakeLLM(), 'verifier': FakeLLM(), 'judge': FakeLLM(model='j')})
    cli.main(['--dataset', str(write_dataset(tmp_path)), '--arms', 'baseline,system@bm25_plain', '--out', str(tmp_path / 'run'), '--cache', str(tmp_path / 'c')])
    out = tmp_path / 'run'
    assert {'predictions.jsonl', 'judgments.jsonl', 'metrics.json', 'results.md'} <= {p.name for p in out.iterdir()}
    metrics = json.loads((out / 'metrics.json').read_text())['metrics']
    assert metrics['system@bm25_plain']['all']['groundedness'] == 1
    status = json.loads((out / 'status.json').read_text())
    assert status['complete'] and status['completed_pairs'] == status['expected_pairs'] == 6
    assert len((out / 'progress.jsonl').read_text().splitlines()) == 6


@pytest.mark.parametrize('transient_code', ['MODEL_RATE_LIMITED', 'MODEL_OVERLOADED'])
def test_rate_limits_retry_but_auth_errors_do_not(transient_code):
    from backend.models.review_llm import ReviewModelError
    from evaluation.harness.runner import RetryingLLM
    class Limited:
        calls = 0
        def complete(self):
            self.calls += 1
            if self.calls < 3:
                raise ReviewModelError(transient_code, 'limited')
            return {'ok': True}
    delays, logs = [], []
    model = Limited()
    assert RetryingLLM(model, logs.append, sleep=delays.append).complete() == {'ok': True}
    assert delays == [15, 30] and model.calls == 3
    class Broken:
        def complete(self):
            raise ReviewModelError('MODEL_AUTH_FAILED', 'invalid', False)
    with pytest.raises(ReviewModelError):
        RetryingLLM(Broken(), logs.append, sleep=delays.append).complete()
    assert delays == [15, 30]
    model = Limited()
    with pytest.raises(ReviewModelError):
        RetryingLLM(model, logs.append, attempts=2, sleep=delays.append).complete()
    assert model.calls == 2


def test_verification_compacts_metadata_without_dropping_context(tmp_path):
    from evaluation.harness.arms import run_system
    from backend.drafting_engine import source_packet
    q = load(write_dataset(tmp_path))[0]
    _, original = source_packet(q['documents'], q['chunks'])
    class Inspector(FakeLLM):
        def complete(self, messages, schema, cancelled=None):
            if messages[0]['content'] == CHECK:
                context = json.loads(messages[1]['content'])
                packet = context['sources']
                restored = [{'source_id': p['source_id'], 'text': p['text'], **context['documents'][p['document_id']]} for p in packet]
                assert restored == original
            return super().complete(messages, schema, cancelled)
    result = run_system(q['question'], q['documents'], q['chunks'], FakeLLM(), Inspector())
    assert result['claims']


def test_packet_context_preserves_all_metadata_and_source_ids():
    from evaluation.harness.arms import packet_context
    packet = [{'source_id': 'E1', 'text': 'First.', 'document_name': 'A', 'document_type': 'statute', 'jurisdiction': 'IN', 'user_provided': False},
              {'source_id': 'E2', 'text': 'Second.', 'document_name': 'A', 'document_type': 'statute', 'jurisdiction': 'IN', 'user_provided': False},
              {'source_id': 'E3', 'text': 'Third.', 'document_name': 'B', 'document_type': 'contract', 'jurisdiction': None, 'user_provided': False}]
    context = packet_context(packet)
    assert len(context['documents']) == 2
    assert [{'source_id': p['source_id'], 'text': p['text'], **context['documents'][p['document_id']]} for p in context['sources']] == packet
    repeated = [{**packet[0], 'source_id': f'E{i}'} for i in range(30)]
    assert len(json.dumps(packet_context(repeated))) < len(json.dumps(repeated))


def test_checkpoints_survive_interruption(tmp_path):
    queries = load(write_dataset(tmp_path))
    saved = []
    def checkpoint(prediction, judgment):
        saved.append((prediction, judgment))
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run(queries, ['baseline'], {'baseline': FakeLLM(), 'judge': FakeLLM()}, checkpoint=checkpoint)
    assert len(saved) == 1 and saved[0][0]['id'] == queries[0]['id']


def test_context_budget_is_shared_across_arms(tmp_path):
    queries = load(write_dataset(tmp_path))
    models = {'baseline': FakeLLM(), 'chat': FakeLLM(), 'verifier': FakeLLM(), 'judge': FakeLLM()}
    predictions, _, _ = run(queries, ['baseline', 'system'], models, context_characters=1)
    assert all(p['retrieved_chunk_ids'] == [] and p['claims'] == [] for p in predictions)
    assert all(p['context_recall'] == 0 for p in predictions if p['id'] != 'none')


def test_judge_cache_distinguishes_quoted_spans_and_questions(tmp_path):
    model = FakeLLM(model='independent')
    judge = Judge(model, tmp_path / 'cache')
    sources = [{'id': 'c1', 'text': FEE + '\n' + FILLER}]
    claim = {'text': 'The service fee is INR 5000.',
             'citations': [{'source_id': 'E1', 'chunk_id': 'c1', 'quote': FEE}]}
    judge.judge('What is the fee?', [claim], sources)
    assert judge.judge('What is the fee?', [claim], sources)[0]['source'] == 'cache'
    different_quote = {**claim, 'citations': [{**claim['citations'][0], 'quote': FILLER}]}
    judge.judge('What is the fee?', [different_quote], sources)
    judge.judge('What is payable?', [claim], sources)
    assert model.calls == 3
