"""Prepare a bounded legal-text pilot from downloaded Parquet; never invent task labels."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def normalized_text(text):
    return ' '.join(str(text or '').split())


def convert(row, source):
    is_act = bool(row.get('act_id'))
    is_judgment = bool(row.get('case_id'))
    text_field = 'text' if is_act or is_judgment else 'headnote_text'
    text = normalized_text(row.get(text_field))
    if len(text) < 200:
        return None
    key = str(row.get('act_id') or row.get('case_id') or row.get('source_pdf_s3_url') or row.get('case_metadata_id') or '')
    if not key:
        return None
    # All sections from an Act stay in one split; cases use their original PDF URL.
    document_id = hashlib.sha256(key.encode()).hexdigest()
    bucket = int(document_id[:8], 16) % 100
    return {'text': text, 'document_id': document_id,
            'split': 'test' if bucket < 15 else 'validation' if bucket < 30 else 'train',
            'provenance': {'file': source, 'original_id': key,
                           'source_url': row.get('source_url') or row.get('source_pdf_s3_url'),
                           'field': text_field},
            'objective': 'raw-text domain adaptation, not workflow SFT'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-documents-per-file', type=int, default=200)
    args = parser.parse_args()
    if args.max_documents_per_file <= 0:
        parser.error('Document limit must be positive.')
    import pyarrow.parquet as pq
    args.out.parent.mkdir(parents=True, exist_ok=True)
    counts, splits, digests = Counter(), Counter(), set()
    with args.out.open('x', encoding='utf-8') as output:
        for path in args.input:
            documents = set()
            for batch in pq.ParquetFile(path).iter_batches(batch_size=128):
                for row in batch.to_pylist():
                    counts['inspected_rows'] += 1
                    item = convert(row, str(path))
                    if item is None:
                        counts['missing_or_short_text'] += 1
                        continue
                    if item['document_id'] not in documents and len(documents) >= args.max_documents_per_file:
                        continue
                    digest = hashlib.sha256(item['text'].encode()).hexdigest()
                    if digest in digests:
                        counts['duplicate_text'] += 1
                        continue
                    documents.add(item['document_id']); digests.add(digest)
                    output.write(json.dumps(item, ensure_ascii=False) + '\n')
                    counts['text_rows'] += 1; splits[item['split']] += 1
            counts['documents'] += len(documents)
    report = {'counts': dict(counts), 'splits': dict(splits), 'inputs': [str(p) for p in args.input],
              'max_documents_per_file': args.max_documents_per_file,
              'objective': 'bounded domain-adaptation pilot; not a full-dataset or workflow-specialist training set',
              'limitations': ['Source headnotes are not verified legal answers.', 'Only exact normalized text deduplication and stable original-document grouping are performed; near-duplicate and benchmark-overlap audits remain required before production training.']}
    args.out.with_suffix('.report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
