# Retrieval ablation: evaluation/datasets/public_dev.jsonl

Answerable queries with gold spans; split filter: all.

## Split: all (10 queries)

| Retriever | recall@5 | mrr | ndcg@5 | recall@10 | ndcg@10 |
|---|---|---|---|---|---|
| hybrid | 0.900 | 0.719 | 0.756 | 0.950 | 0.775 |
| bm25 | 0.900 | 0.729 | 0.763 | 0.950 | 0.782 |
| dense | 0.900 | 0.683 | 0.727 | 0.950 | 0.745 |
| bm25_plain | 0.900 | 0.729 | 0.763 | 0.950 | 0.782 |

## Split: dev (7 queries)

| Retriever | recall@5 | mrr | ndcg@5 | recall@10 | ndcg@10 |
|---|---|---|---|---|---|
| hybrid | 0.857 | 0.671 | 0.704 | 0.929 | 0.731 |
| bm25 | 0.857 | 0.708 | 0.733 | 0.929 | 0.761 |
| dense | 0.857 | 0.643 | 0.682 | 0.929 | 0.707 |
| bm25_plain | 0.857 | 0.708 | 0.733 | 0.929 | 0.761 |

## Split: heldout (3 queries)

| Retriever | recall@5 | mrr | ndcg@5 | recall@10 | ndcg@10 |
|---|---|---|---|---|---|
| hybrid | 1.000 | 0.833 | 0.877 | 1.000 | 0.877 |
| bm25 | 1.000 | 0.778 | 0.833 | 1.000 | 0.833 |
| dense | 1.000 | 0.778 | 0.833 | 1.000 | 0.833 |
| bm25_plain | 1.000 | 0.778 | 0.833 | 1.000 | 0.833 |
