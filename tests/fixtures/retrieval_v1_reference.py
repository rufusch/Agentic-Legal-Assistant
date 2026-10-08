"""Local BM25 + dense latent-semantic retrieval, fused with reciprocal ranks.

LSA is a corpus-trained dense baseline, not a pretrained legal embedding model.
Only ciphertext is stored on disk; matrices are derived in memory per tenant.
"""
import math
import re
from collections import Counter

import numpy as np

STOP = set('the a an is are to of in and or for on by with as be it this that from'.split())


def terms(text):
    text = re.sub(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])', ' ', text)
    return [t for t in re.findall(r'\w+', text.casefold()) if t not in STOP and len(t) > 1]


def search(chunks, query, limit=10):
    if not chunks:
        return []
    counts = [Counter(terms(c['text'])) for c in chunks]
    query_terms = Counter(terms(query))
    if not query_terms:
        return []
    n = len(counts)
    df = Counter(t for count in counts for t in count)
    # OCR can omit spaces: recover query terms inside recognized runs for sparse retrieval.
    for count in counts:
        for term in query_terms:
            if len(term) >= 4 and not count[term]:
                count[term] = sum(value for token, value in list(count.items()) if term in token and len(token) > len(term)) * .5
                if count[term]:
                    df[term] += 1
    average = sum(sum(c.values()) for c in counts) / max(n, 1)
    lexical = []
    for count in counts:
        length = sum(count.values())
        score = sum(math.log(1 + (n - df[t] + .5) / (df[t] + .5)) * count[t] * 2.2 / (count[t] + 1.2 * (.25 + .75 * length / max(average, 1))) for t in query_terms if count[t])
        lexical.append(score)
    # Keep matrix bounded. Most frequent non-stop terms form the local vocabulary.
    vocabulary = sorted(df, key=lambda t: (-df[t], t))[:2048]
    columns = {t: i for i, t in enumerate(vocabulary)}
    matrix = np.zeros((n, len(vocabulary)), dtype=np.float32)
    vector = np.zeros(len(vocabulary), dtype=np.float32)
    for term, column in columns.items():
        idf = math.log((1 + n) / (1 + df[term])) + 1
        for row, count in enumerate(counts):
            if count[term]:
                matrix[row, column] = (1 + math.log(count[term])) * idf
        if query_terms[term]:
            vector[column] = (1 + math.log(query_terms[term])) * idf
    dense = np.zeros(n)
    if matrix.size and np.linalg.norm(vector):
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        normalized = matrix / np.maximum(norms, 1e-8)
        # Randomized low-rank range projection keeps large corpora bounded.
        rank = min(64, n, len(vocabulary))
        if rank < min(n, len(vocabulary)):
            rng = np.random.default_rng(42)
            projection = normalized @ rng.standard_normal((len(vocabulary), rank)).astype(np.float32)
            basis, _ = np.linalg.qr(projection)
            _, _, vt = np.linalg.svd(basis.T @ normalized, full_matrices=False)
        else:
            _, _, vt = np.linalg.svd(normalized, full_matrices=False)
        latent = normalized @ vt[:rank].T
        q = vector @ vt[:rank].T
        dense = (latent @ q) / np.maximum(np.linalg.norm(latent, axis=1) * np.linalg.norm(q), 1e-8)
    ranks = {}
    for scores in (lexical, dense):
        for rank, index in enumerate(sorted(range(n), key=lambda i: (-float(scores[i]), chunks[i]['id'])), 1):
            if scores[index] > 1e-6:
                ranks[index] = ranks.get(index, 0) + 1 / (60 + rank)
    selected = sorted(ranks, key=lambda i: (-ranks[i], -lexical[i], chunks[i]['id']))[:limit]
    return [{**chunks[i], 'score': round(ranks[i], 6), 'lexical_score': round(lexical[i], 4), 'dense_score': round(float(dense[i]), 4)} for i in selected]
