"""Pluggable dense embedders. Selection (env LEXIMIND_EMBEDDINGS):
  ollama              -> Ollama /api/embed  (LEXIMIND_EMBED_MODEL, LEXIMIND_EMBED_BASE_URL)
  compatible | openai -> OpenAI-style /v1/embeddings (+ LEXIMIND_EMBED_API_KEY)
  fastembed           -> local ONNX model via optional `fastembed` package (LEXIMIND_EMBED_MODEL)
  lsa | unset         -> no neural embedder; retrieval uses corpus-fitted LSA.
Embeddings are cached in-process (bounded LRU keyed by text hash). Callers must treat any
exception as "fall back to LSA"; get_embedder() itself never raises.
"""
import hashlib
import os
from collections import OrderedDict

import numpy as np


class Embedder:
    name = 'base'
    max_cache = 20000

    def __init__(self):
        self._cache = OrderedDict()

    def _embed(self, texts):
        raise NotImplementedError

    def embed(self, texts):
        keys = [hashlib.sha256(t.encode('utf-8', 'ignore')).hexdigest() for t in texts]
        missing = list(dict.fromkeys(k for k in keys if k not in self._cache))
        if missing:
            lookup = dict(zip(keys, texts))
            for i in range(0, len(missing), 64):
                batch = missing[i:i + 64]
                vectors = self._embed([lookup[k] for k in batch])
                if len(vectors) != len(batch):
                    raise ValueError('Embedding count mismatch.')
                for k, v in zip(batch, vectors):
                    self._cache[k] = np.asarray(v, dtype=np.float32)
        out = []
        for k in keys:
            self._cache.move_to_end(k)
            out.append(self._cache[k])
        while len(self._cache) > self.max_cache:
            self._cache.popitem(last=False)
        matrix = np.vstack(out)
        return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8)


class OllamaEmbedder(Embedder):
    def __init__(self, model=None, base_url=None, timeout=60, transport=None):
        super().__init__()
        self.model = model or os.getenv('LEXIMIND_EMBED_MODEL', 'nomic-embed-text')
        self.base_url = (base_url or os.getenv('LEXIMIND_EMBED_BASE_URL', 'http://127.0.0.1:11434')).rstrip('/')
        self.timeout, self.transport = timeout, transport
        self.name = f'ollama:{self.model}'

    def _embed(self, texts):
        import httpx
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            r = client.post(self.base_url + '/api/embed', json={'model': self.model, 'input': [t[:8000] for t in texts]})
            r.raise_for_status()
            return r.json()['embeddings']


class CompatibleEmbedder(Embedder):
    def __init__(self, model=None, base_url=None, api_key=None, timeout=60, transport=None):
        super().__init__()
        self.model = model or os.getenv('LEXIMIND_EMBED_MODEL', 'text-embedding-3-small')
        self.base_url = (base_url or os.getenv('LEXIMIND_EMBED_BASE_URL', 'http://127.0.0.1:1234')).rstrip('/')
        self.api_key = api_key if api_key is not None else os.getenv('LEXIMIND_EMBED_API_KEY', '')
        self.timeout, self.transport = timeout, transport
        self.name = f'compatible:{self.model}'

    def _embed(self, texts):
        import httpx
        url = self.base_url + ('/embeddings' if self.base_url.endswith('/v1') else '/v1/embeddings')
        headers = {'Authorization': 'Bearer ' + self.api_key} if self.api_key else {}
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            r = client.post(url, json={'model': self.model, 'input': [t[:8000] for t in texts]}, headers=headers)
            r.raise_for_status()
            return [row['embedding'] for row in sorted(r.json()['data'], key=lambda d: d.get('index', 0))]


class FastEmbedEmbedder(Embedder):
    def __init__(self, model=None):
        super().__init__()
        from fastembed import TextEmbedding  # optional dependency
        self.model = model or os.getenv('LEXIMIND_EMBED_MODEL', 'BAAI/bge-small-en-v1.5')
        self._model = TextEmbedding(self.model)
        self.name = f'fastembed:{self.model}'

    def _embed(self, texts):
        return list(self._model.embed(texts))


_DEFAULT = {}


def get_embedder(kind=None):
    """Return the configured embedder or None (=> LSA). Cached per kind; never raises."""
    kind = (kind or os.getenv('LEXIMIND_EMBEDDINGS', '')).strip().lower()
    if kind in ('', 'lsa', 'none', 'off'):
        return None
    if kind not in _DEFAULT:
        try:
            _DEFAULT[kind] = {'ollama': OllamaEmbedder, 'compatible': CompatibleEmbedder, 'openai': CompatibleEmbedder, 'fastembed': FastEmbedEmbedder}[kind]()
        except Exception:
            _DEFAULT[kind] = None
    return _DEFAULT[kind]
