# Retrieval ablation — measured, not asserted

Two independent query sets, same corpus (`corpus/public-starter`: Indian Contract Act 1872,
Supreme Court bail judgment). No LLM involved: these numbers are pure retrieval.

## Set A — `scripts/bench_retrieval.py` (24 queries, written while tuning `full`)

| mode | R@1 | R@5 | R@10 | MRR@10 | ms/q |
|---|---|---|---|---|---|
| bm25 | 0.75 | 0.96 | 1.00 | 0.844 | 1 |
| lsa | 0.71 | 0.88 | 0.88 | 0.765 | 1 |
| hybrid (previous default) | 0.75 | 0.92 | 0.96 | 0.801 | 80 |
| hybrid+rewrite | 0.71 | 0.92 | 0.96 | 0.800 | 2 |
| **full (new default)** | **0.83** | **0.96** | **1.00** | **0.884** | 12 |

## Set B — `evaluation/datasets/public_dev.jsonl` (13 queries, written independently)

| mode | recall@5 | MRR | nDCG@5 | recall@10 | nDCG@10 |
|---|---|---|---|---|---|
| hybrid | 0.900 | 0.719 | 0.756 | 0.950 | 0.775 |
| bm25_plain | 0.900 | 0.729 | 0.763 | 0.950 | 0.782 |
| hybrid+rewrite | 0.900 | 0.722 | 0.756 | 0.950 | 0.777 |
| full | 0.900 | 0.650 | 0.699 | **1.000** | 0.740 |

## Honest reading

- `full` wins clearly on **statute-section queries** ("Section 171 Indian Contract Act",
  "u/s 70 ICA", "Sec. 73 ICA"), which the previous default missed entirely. That is the
  query shape judges are most likely to bring for Indian law.
- `full` wins on **recall@10** on both sets (1.000 vs 0.950/0.96). Recall is what matters for a
  high-recall-bias grounded pipeline: the verifier drops bad chunks, it cannot recover missing ones.
- `full` **loses on MRR on set B** (0.650 vs 0.719). Set A was written by the same engineer who
  tuned `full`, so set A overstates the gain; set B is the more trustworthy comparison for ranking.
- The old `hybrid` default **does not beat plain BM25** on either set. The LSA "dense" half was
  not earning its cost.
- Neither set used real embeddings or the LLM reranker (no model server in the build sandbox),
  so `full` here is still LSA-backed. Both are expected to improve MRR; this must be re-measured.

Set B is the set to quote. Do not present set A as a held-out result.
