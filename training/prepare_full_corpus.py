"""Stream every downloaded Parquet into deduplicated, document-split JSONL shards."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from training.prepare_domain_corpus import convert


def prepare(inputs, out, shard_rows=100000):
    import pyarrow.parquet as pq
    out.mkdir(parents=True, exist_ok=False)
    state = {'complete': False, 'inputs': [str(p) for p in inputs], 'inspected_rows': 0,
             'accepted_rows': 0, 'duplicates': 0, 'missing_text_or_id': 0,
             'splits': {'train': 0, 'validation': 0, 'test': 0},'shard_sha256':{},'text_characters':0,
             'objective': 'full-corpus raw-text adaptation, not workflow SFT',
             'limitations': ['Exact normalized-text deduplication only; cross-source case identity and near-duplicate audit remain necessary.',
                             'No certification of source accuracy, currency or task competence.']}
    db = sqlite3.connect(out / 'dedup.sqlite3')
    db.execute('CREATE TABLE hashes (hash TEXT PRIMARY KEY) WITHOUT ROWID')
    output = None;hasher=None
    def checkpoint():
        db.commit()
        temp = out / 'manifest.tmp'
        temp.write_text(json.dumps(state, indent=2), encoding='utf-8')
        temp.replace(out / 'manifest.json')
    checkpoint()
    try:
        for path in inputs:
            state['current_input'] = str(path)
            print('Preparing ' + str(path), flush=True)
            for batch in pq.ParquetFile(path).iter_batches(batch_size=128):
                for row in batch.to_pylist():
                    state['inspected_rows'] += 1
                    item = convert(row, str(path))
                    if item is None:
                        state['missing_text_or_id'] += 1
                        continue
                    digest = hashlib.sha256(item['text'].encode()).hexdigest()
                    if not db.execute('INSERT OR IGNORE INTO hashes VALUES (?)', (digest,)).rowcount:
                        state['duplicates'] += 1
                        continue
                    if state['accepted_rows'] % shard_rows == 0:
                        if output:
                            state['shard_sha256'][Path(output.name).name]=hasher.hexdigest();output.close()
                        output = (out / f"part-{state['accepted_rows']//shard_rows:06}.jsonl").open('x', encoding='utf-8',newline='\n')
                        hasher=hashlib.sha256()
                    line=json.dumps(item, ensure_ascii=False) + '\n'
                    output.write(line);hasher.update(line.encode('utf-8'))
                    state['accepted_rows'] += 1
                    state['text_characters']+=len(item['text'])
                    state['splits'][item['split']] += 1
                if state['inspected_rows'] % 12800 == 0:
                    output.flush() if output else None
                    checkpoint()
            checkpoint()
        if not state['accepted_rows']: raise ValueError('No usable legal text.')
        if output:
            state['shard_sha256'][Path(output.name).name]=hasher.hexdigest();output.close();output = None
        state['complete'] = True
        state['shards'] = [p.name for p in sorted(out.glob('part-*.jsonl'))]
        checkpoint()
    except BaseException as exc:
        state['error_type'] = type(exc).__name__
        checkpoint()
        raise
    finally:
        if output: output.close()
        db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--downloads', type=Path, default=Path('datasets/india-law/downloads'))
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    paths = [];snapshots={}
    for source in ('kanoon', 'vaquill'):
        folder = a.downloads / source
        status = json.loads((folder / 'download-status.json').read_text())
        if not status.get('complete'): raise SystemExit(f'{source} download is incomplete; full-corpus preparation refused.')
        snapshots[source]=status
        paths.extend(sorted(folder.rglob('*.parquet')))
    prepare(paths, a.out)
    path=a.out/'manifest.json';state=json.loads(path.read_text());state['source_snapshots']=snapshots
    path.write_text(json.dumps(state,indent=2),encoding='utf-8')


if __name__ == '__main__': main()
