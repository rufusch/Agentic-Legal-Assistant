"""Paired evaluation runner: baseline RAG vs grounded pipeline (+ ablations), judged claim by claim.

  python -m scripts.run_eval --dataset evaluation/datasets/public_dev.jsonl \
      --arms baseline,system,system_no_verify --split all --out evaluation/runs/demo
  python -m scripts.run_eval --dataset evaluation/datasets/public_dev.jsonl --retrieval-only \
      --retrievers hybrid,bm25,dense,bm25_plain --out evaluation/runs/retrieval

Arms: baseline, system, system_no_verify, system_no_numeric, system_no_authority, system_generation_only.
Append @<retriever> to an arm (system@bm25) for a retrieval ablation. Models come from env vars per role:
LEXIMIND_{BASELINE,CHAT,VERIFIER,JUDGE}_LLM_PROVIDER/_BASE_URL/_LLM_MODEL/_API_KEY (fallback LEXIMIND_LLM_*).
"""
import argparse
import hashlib
from pathlib import Path

from evaluation.harness import retrievers
from evaluation.harness.dataset import load
from evaluation.harness.runner import build_llms, judge_warnings, markdown, model_name, retrieval_markdown, run, stderr, write


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--arms', default='baseline,system')
    p.add_argument('--split', default='all', help="'all', 'dev' or 'heldout'")
    p.add_argument('--retrieval', default='hybrid', help='default retriever for arms without @variant')
    p.add_argument('--retrievers', default='hybrid,bm25,dense,bm25_plain', help='retrieval-only variants')
    p.add_argument('--retrieval-only', action='store_true', help='LLM-free retrieval ablation table')
    p.add_argument('--limit', type=int)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--cache', type=Path, default=Path('evaluation/runs/.judge-cache'))
    args = p.parse_args(argv)

    queries = load(args.dataset, args.split, args.limit)
    if not queries:
        raise SystemExit('No queries selected.')
    meta = {'dataset': str(args.dataset), 'dataset_sha256': hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
            'split': args.split, 'queries': len(queries), 'query_ids': [q['id'] for q in queries], 'retrieval': args.retrieval}
    if args.retrieval_only:
        names = [n.strip() for n in args.retrievers.split(',') if n.strip()]
        table = retrievers.evaluate_retrievers(queries, names)
        report = retrieval_markdown(table, meta)
        write(args.out, **{'retrieval.json': {**meta, 'retrievers': table}, 'results.md': report})
        print(report)
        return table

    arms = [a.strip() for a in args.arms.split(',') if a.strip()]
    llms = build_llms(arms)
    meta.update(arms=arms, models={k: model_name(v) for k, v in llms.items()}, judge_model=model_name(llms['judge']), warnings=judge_warnings(llms))
    for w in meta['warnings']:
        stderr('WARNING:', w)
    for role, llm in llms.items():
        status = llm.status() if hasattr(llm, 'status') else {'ready': True}
        if not status.get('ready'):
            stderr(f'WARNING: {role} model {model_name(llm)} not ready ({status.get("reason")}); its queries will be recorded as failures.')
    predictions, judgments, metrics = run(queries, arms, llms, args.retrieval, args.cache, stderr)
    report = markdown(metrics, meta)
    write(args.out, **{'predictions.jsonl': predictions, 'judgments.jsonl': judgments, 'metrics.json': {**meta, 'metrics': metrics}, 'results.md': report})
    print(report)
    return metrics


if __name__ == '__main__':
    main()
