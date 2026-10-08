import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SPECS = {
    'review': ['payment', 'termination', 'parties', 'governing_law', 'missing_material', 'other'],
    'drafting': ['requirement', 'fact', 'authority', 'placeholder', 'draft_language', 'other'],
    'research': ['statute', 'judgment', 'secondary', 'conflict', 'fact', 'other'],
    'chat': ['answerable', 'partially_answerable', 'not_answerable'],
    'novelty': ['task', 'evidence', 'clarification', 'other'],
}


def features(text, dimension=512):
    words = re.findall(r'\w+', text.casefold())
    words += [f'{a}_{b}' for a,b in zip(words, words[1:])]
    vector = np.zeros(dimension, dtype=np.float64)
    for word in words:
        digest = hashlib.sha256(word.encode()).digest()
        vector[int.from_bytes(digest[:4], 'big') % (dimension - 1)] += 1
    norm = np.linalg.norm(vector)
    if norm:
        vector /= norm
    vector[-1] = 1  # Bias; deterministic hashing permits inference on new vocabulary.
    return vector


@dataclass
class WorkflowModel:
    workflow: str
    artifact: dict | None = None

    @property
    def metadata(self):
        return {'id': f'leximind-{self.workflow}', 'workflow': self.workflow, 'version': self.artifact['version'] if self.artifact else 'extractive-baseline-v1' if self.workflow == 'review' else 'not-implemented', 'kind': 'trained_topic_classifier' if self.artifact else 'extractive_rules' if self.workflow == 'review' else 'reserved', 'available': self.workflow == 'review', 'trainable': True, 'labels': SPECS[self.workflow], 'output_schema': 'review-report-v1' if self.workflow == 'review' else f'{self.workflow}-v1'}

    def classify(self, text):
        if self.artifact:
            values = features(text, self.artifact['dimension']) @ np.asarray(self.artifact['weights'])
            probabilities = np.exp(values - np.max(values))
            probabilities /= probabilities.sum()
            index = int(np.argmax(probabilities))
            return self.artifact['labels'][index], float(probabilities[index])
        rules = [('missing_material', r'not attached|not included|missing|no signatures|unsigned'), ('payment', r'\bpay(?:ment|able)?\b|invoice|remuneration'), ('termination', r'terminat|written notice|notice period'), ('governing_law', r'governing law|jurisdiction'), ('parties', r'between .+ and |applicant|respondent|plaintiff|defendant')]
        for label, pattern in rules:
            if re.search(pattern, text, re.I):
                return label, .8
        return 'other', .5


class ModelRegistry:
    def __init__(self, paths=None):
        paths = paths if paths is not None else {w:os.getenv(f'LEXIMIND_{w.upper()}_MODEL') for w in SPECS}
        self.models = {}
        for workflow in SPECS:
            artifact = None
            if paths.get(workflow):
                path = Path(paths[workflow])
                if path.stat().st_size > 10 * 1024 * 1024:
                    raise ValueError('Model artifact exceeds size limit')
                artifact = json.loads(path.read_text(encoding='utf-8'))
                dimension = artifact.get('dimension',0)
                if artifact.get('format') != 'hashed-softmax-v1' or artifact.get('workflow') != workflow or artifact.get('labels') != SPECS[workflow] or not 32 <= dimension <= 2048:
                    raise ValueError(f'Invalid {workflow} model artifact')
                weights = np.asarray(artifact.get('weights'), dtype=float)
                if weights.shape != (dimension,len(SPECS[workflow])) or not np.isfinite(weights).all():
                    raise ValueError('Invalid model weights')
            self.models[workflow] = WorkflowModel(workflow, artifact)

    def get(self, workflow):
        return self.models[workflow]

    def describe(self):
        return [self.models[w].metadata for w in SPECS]
