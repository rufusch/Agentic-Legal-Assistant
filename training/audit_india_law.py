"""Audit a KanoonGPT Parquet partition without inventing supervised targets.

python training/audit_india_law.py --input datasets/india-law/raw/kanoon-1950.parquet --out datasets/india-law/audit
Split membership is an initial case-ID partition, not cross-corpus deduplication.
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def split_for(case_id):
    bucket = int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16) % 100
    return 'test' if bucket < 15 else 'validation' if bucket < 30 else 'train'


def audit_record(row):
    case_id = str(row.get('case_metadata_id') or row.get('id') or '')
    if not case_id:
        raise ValueError('Missing stable case identifier')
    headnote = str(row.get('headnote_text') or '')
    quality = row.get('quality_json') or '{}'
    try:
        quality = json.loads(quality) if isinstance(quality, str) else quality
    except ValueError:
        quality = {'invalid_json': True}
    return {'case_id': case_id, 'split': split_for(case_id),
            'source_pdf_url': row.get('source_pdf_s3_url'),
            'source_json_url': row.get('source_json_s3_url'),
            'headnote_characters': len(headnote),
            'headnote_sha256': hashlib.sha256(headnote.encode()).hexdigest() if headnote else None,
            'quality': quality,
            'supervised_training_ready': False,
            'reason': 'No task-specific validated prompt/completion targets; metadata/headnotes are source material only.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    import pyarrow.parquet as pq
    args.out.mkdir(parents=True, exist_ok=True)
    counts, splits, seen_ids, seen_text = Counter(), Counter(), set(), set()
    with (args.out / 'case-split-manifest.jsonl').open('w', encoding='utf-8') as stream:
        for batch in pq.ParquetFile(args.input).iter_batches(batch_size=256):
            for row in batch.to_pylist():
                item = audit_record(row)
                counts['records'] += 1
                splits[item['split']] += 1
                counts['with_headnote'] += bool(item['headnote_characters'])
                counts['duplicate_case_ids'] += item['case_id'] in seen_ids
                seen_ids.add(item['case_id'])
                digest = item['headnote_sha256']
                if digest:
                    counts['duplicate_headnote_hashes'] += digest in seen_text
                    seen_text.add(digest)
                stream.write(json.dumps(item, ensure_ascii=False) + '\n')
    report = {'input': str(args.input), 'counts': dict(counts), 'initial_case_splits': dict(splits),
              'supervised_examples': 0, 'trained_models': [],
              'workflow_readiness': {role: 'blocked: validated task targets required' for role in ('review', 'drafting', 'research', 'chat', 'verifier')},
              'limitations': ['Single partition inspection only.', 'Case-ID splitting does not prevent duplicates across other IDs or datasets. Cross-source case/content deduplication is required before training.', 'Upstream metadata and headnotes have not been validated against original PDFs.', 'No training data or model weights are produced by this audit.']}
    (args.out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
