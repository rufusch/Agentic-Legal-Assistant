"""Run arms over a dataset, judge every claim, compute metrics and write a paste-ready report."""
import json
import sys
from pathlib import Path

from evaluation.harness import retrievers
from evaluation.harness.arms import llm_for_role, model_name, parse_arm, run_arm
from evaluation.harness.judge import Judge
from evaluation.harness.metrics import summarize


def _query_summary(q):
    return {'id': q['id'], 'split': q['split'], 'workflow': q['workflow'], 'answerable': q['answerable'], 'gold_chunk_ids': q['gold_chunk_ids']}


def build_llms(arms):
    names = {parse_arm(a)[0] for a in arms}
    llms = {}
    if 'baseline' in names:
        llms['baseline'] = llm_for_role('baseline')
    if names - {'baseline'}:
        llms['chat'] = llm_for_role('chat'); llms['verifier'] = llm_for_role('verifier')
    llms['judge'] = llm_for_role('judge')
    return llms


def judge_warnings(llms):
    judge = model_name(llms.get('judge')) if llms.get('judge') else None
    gens = {model_name(v) for k, v in llms.items() if k != 'judge' and v is not None}
    if judge and judge in gens:
        return [f'Judge model {judge!r} is also a generator; use a different model family (LEXIMIND_JUDGE_LLM_MODEL) to avoid self-preference bias.']
    return []


def run(queries, arms, llms, retrieval='hybrid', cache_dir=None, log=lambda *_: None):
    """Returns (predictions, judgments, metrics). Model errors are recorded per query, never fatal."""
    judge = Judge(llms.get('judge'), cache_dir)
    predictions, judgments, by_arm = [], [], {}
    for spec in arms:
        name, variant = parse_arm(spec)
        fn = retrievers.get(variant or retrieval)
        for q in queries:
            hits = retrievers.budgeted(fn(q['chunks'], q['question'], 10))
            ids = [c['id'] for c in hits]
            gold = set(q['gold_chunk_ids'])
            pred = {'arm': spec, 'id': q['id'], 'split': q['split'], 'retriever': variant or retrieval, 'retrieved_chunk_ids': ids,
                    'context_recall': round(len(gold & set(ids)) / len(gold), 4) if gold else None}
            try:
                pred.update(run_arm(name, q, hits, llms))
            except Exception as exc:  # record and continue: a crash is a non-answer, not a skipped query
                pred.update(claims=[], error=f'{type(exc).__name__}: {getattr(exc, "message", exc)}'[:500])
            try:
                judged = judge.judge(q['question'], pred['claims'], hits)
            except Exception as exc:
                judged = [{'claim': c['text'], 'label': None, 'reason': f'judge error: {exc}'[:300], 'source': 'error', 'deterministic_flags': []} for c in pred['claims']]
            predictions.append(pred)
            judgments.append({'arm': spec, 'id': q['id'], 'judgments': judged})
            by_arm.setdefault(spec, []).append({'query': _query_summary(q), 'prediction': pred, 'judgments': judged})
            log(f'[{spec}] {q["id"]}: {len(pred["claims"])} claims' + (f' ERROR {pred["error"]}' if pred.get('error') else ''))
    return predictions, judgments, summarize(by_arm)


COLUMNS = [('groundedness', 'Grounded'), ('strict_groundedness', 'Strict'), ('fabricated_claims', 'Fabricated'),
           ('claims', 'Claims'), ('answer_coverage', 'Coverage'), ('correct_abstention', 'Abstain OK'),
           ('context_recall', 'Ctx recall'), ('failures', 'Failures'), ('mean_latency_s', 'Latency s')]


def _fmt(v):
    return '-' if v is None else f'{v:.3f}' if isinstance(v, float) else str(v)


def markdown(metrics, meta):
    lines = [f"# Evaluation results: {meta.get('dataset')}", '',
             f"Queries: {meta.get('queries')} | split: {meta.get('split')} | default retriever: {meta.get('retrieval')} | judge: {meta.get('judge_model')}", '']
    for w in meta.get('warnings', []):
        lines.append(f'> WARNING: {w}')
    splits = sorted({s for arm in metrics.values() for s in arm}, key=lambda s: (s != 'all', s))
    for split in splits:
        lines += ['', f'## Split: {split}', '', '| Arm | ' + ' | '.join(h for _, h in COLUMNS) + ' |', '|' + '---|' * (len(COLUMNS) + 1)]
        for arm, by_split in metrics.items():
            if split in by_split:
                lines.append(f'| {arm} | ' + ' | '.join(_fmt(by_split[split][k]) for k, _ in COLUMNS) + ' |')
    lines += ['', 'Grounded = (supported + 0.5 x partially supported) / judged claims. Fabricated = cites an unseen source or asserts a',
              'section, citation, case party or number found in no retrieved source (deterministic check) or judged fabricated.']
    return '\n'.join(lines) + '\n'


def retrieval_markdown(table, meta):
    lines = [f"# Retrieval ablation: {meta.get('dataset')}", '', f"Answerable queries with gold spans; split filter: {meta.get('split')}.", '']
    splits = sorted({s for t in table.values() for s in t}, key=lambda s: (s != 'all', s))
    for split in splits:
        metrics = next(t[split] for t in table.values() if split in t)
        keys = [k for k in metrics if k != 'queries']
        lines += [f'## Split: {split} ({metrics["queries"]} queries)', '', '| Retriever | ' + ' | '.join(keys) + ' |', '|' + '---|' * (len(keys) + 1)]
        for name, t in table.items():
            if split in t:
                lines.append(f'| {name} | ' + ' | '.join(_fmt(t[split][k]) for k in keys) + ' |')
        lines.append('')
    return '\n'.join(lines)


def write(out, **files):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    for name, value in files.items():
        path = out / name
        if name.endswith('.jsonl'):
            path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in value), encoding='utf-8')
        elif name.endswith('.json'):
            path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
        else:
            path.write_text(value, encoding='utf-8')
    return out


def stderr(*a):
    print(*a, file=sys.stderr, flush=True)
