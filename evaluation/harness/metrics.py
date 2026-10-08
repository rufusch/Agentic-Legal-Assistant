"""Per-arm metrics from predictions + judgments, and paired comparisons on identical query sets."""
from statistics import mean

WEIGHT = {'supported': 1.0, 'partially_supported': .5, 'unsupported': 0.0, 'fabricated': 0.0}


def _avg(values):
    values = [v for v in values if v is not None]
    return round(mean(values), 4) if values else None


def arm_metrics(rows):
    """rows: [{'query': q-summary, 'prediction': p, 'judgments': [...]}] for ONE arm."""
    labels = [j['label'] for r in rows for j in r['judgments']]
    judged = [l for l in labels if l is not None]
    failed = [r for r in rows if r['prediction'].get('error')]
    ok = [r for r in rows if not r['prediction'].get('error')]
    answerable = [r for r in rows if r['query']['answerable']]
    unanswerable = [r for r in rows if not r['query']['answerable']]
    fabricated = labels.count('fabricated')
    return {
        'queries': len(rows), 'failures': len(failed), 'claims': len(labels), 'unjudged_claims': len(labels) - len(judged),
        'groundedness': round(sum(WEIGHT[l] for l in judged) / len(judged), 4) if judged else None,
        'strict_groundedness': round(judged.count('supported') / len(judged), 4) if judged else None,
        'fabricated_claims': fabricated, 'fabrication_rate': round(fabricated / len(labels), 4) if labels else None,
        'label_counts': {l: labels.count(l) for l in WEIGHT},
        # failures count as non-answers: a crash is not an answer.
        'answer_coverage': round(sum(bool(r['prediction'].get('claims')) and not r['prediction'].get('error') for r in answerable) / len(answerable), 4) if answerable else None,
        'correct_abstention': round(sum(not r['prediction'].get('claims') and not r['prediction'].get('error') for r in unanswerable) / len(unanswerable), 4) if unanswerable else None,
        'context_recall': _avg([r['prediction'].get('context_recall') for r in answerable]),
        'mean_latency_s': _avg([r['prediction'].get('latency_s') for r in ok]),
    }


def summarize(rows_by_arm):
    """{arm: {split: metrics}}; refuses comparison unless every arm ran on the identical query set."""
    sets = {arm: sorted(r['query']['id'] for r in rows) for arm, rows in rows_by_arm.items()}
    if len({tuple(s) for s in sets.values()}) > 1:
        raise ValueError(f'Arms ran on different query sets; refusing to compare: { {a: len(s) for a, s in sets.items()} }')
    for arm, ids in sets.items():
        if len(ids) != len(set(ids)):
            raise ValueError(f'Duplicate predictions for arm {arm}')
    out = {}
    for arm, rows in rows_by_arm.items():
        splits = sorted({r['query']['split'] for r in rows})
        out[arm] = {'all': arm_metrics(rows), **{s: arm_metrics([r for r in rows if r['query']['split'] == s]) for s in splits}}
    return out
