"""Offline training of a separate classifier for each workflow; no automatic deployment."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from backend.models.registry import SPECS, features


def train(workflow, records, version, epochs=200, dimension=512):
    if workflow not in SPECS or not 1 <= epochs <= 2000 or not 32 <= dimension <= 2048:
        raise ValueError('Invalid training configuration')
    if not version or len(version) > 100:
        raise ValueError('A model version is required')
    labels = SPECS[workflow]
    if not records or len(records) > 10000:
        raise ValueError('Supply 1–10000 labeled examples')
    seen = {}
    for r in records:
        if r.get('workflow') != workflow or not r.get('use_for_training') or not r.get('human_approved'):
            raise ValueError('Every example needs matching workflow, human approval and training consent')
        if r.get('label') not in labels or not r.get('text') or len(r['text']) > 10000 or not r.get('group_id'):
            raise ValueError('Invalid label, text or provenance group')
        digest = hashlib.sha256(r['text'].encode()).hexdigest()
        if digest in seen and seen[digest] != r['group_id']:
            raise ValueError('Identical text cannot cross provenance groups')
        seen[digest] = r['group_id']
    groups = sorted({r['group_id'] for r in records}, key=lambda g: hashlib.sha256(g.encode()).hexdigest())
    if len(groups) < 3:
        raise ValueError('At least three independent source groups are required for held-out evaluation')
    heldout = set(groups[:max(1,len(groups)//5)])
    training = [r for r in records if r['group_id'] not in heldout]
    validation = [r for r in records if r['group_id'] in heldout]
    represented = {r['label'] for r in training}
    if len(represented) < 2:
        raise ValueError('Training partition needs at least two labels')
    matrix = np.vstack([features(r['text'],dimension) for r in training])
    targets = np.asarray([labels.index(r['label']) for r in training])
    weights = np.zeros((dimension,len(labels)), dtype=np.float64)
    expected = np.eye(len(labels))[targets]
    for _ in range(epochs):
        logits = matrix @ weights
        logits -= logits.max(axis=1, keepdims=True)
        probabilities = np.exp(logits)
        probabilities /= probabilities.sum(axis=1,keepdims=True)
        weights -= .5 * (matrix.T @ (probabilities - expected) / len(matrix) + .001 * weights)
    predictions = [int(np.argmax(features(r['text'],dimension) @ weights)) for r in validation]
    accuracy = sum(labels[p] == r['label'] for p,r in zip(predictions,validation)) / len(validation)
    dataset_hash = hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()
    return {'format':'hashed-softmax-v1','workflow':workflow,'version':version,'dimension':dimension,'labels':labels,'weights':weights.tolist(),'dataset_sha256':dataset_hash,'evaluation':{'train_examples':len(training),'validation_examples':len(validation),'validation_accuracy':accuracy,'split':'source_group_holdout','training_labels':sorted(represented)},'purpose':'Topic classification only; does not establish legal correctness.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow',choices=SPECS,required=True)
    parser.add_argument('--dataset',required=True)
    parser.add_argument('--version',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--epochs',type=int,default=200)
    args=parser.parse_args()
    source=Path(args.dataset)
    if source.stat().st_size > 50*1024*1024:
        raise ValueError('Dataset exceeds 50 MB')
    records=[json.loads(line) for line in source.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    result=train(args.workflow,records,args.version,args.epochs)
    destination=Path(args.output)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('x',encoding='utf-8') as stream:
        json.dump(result,stream)
    print(json.dumps({'workflow':args.workflow,'version':args.version,'evaluation':result['evaluation'],'artifact':str(destination)}))


if __name__ == '__main__':
    main()
