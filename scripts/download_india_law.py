"""Download pinned public/gated legal datasets locally; rerun to resume.

python -m scripts.download_india_law --source kanoon
python -m scripts.download_india_law --source vaquill
HF_TOKEN is read from the environment and never written to the status file.
"""
import argparse
import json
import os
from pathlib import Path

SOURCES = {
    'kanoon': ('KanoonGPT/indian-case-laws', ['structured/v1/**/*.parquet', 'README.md']),
    'vaquill': ('vaquill/open-india-law', ['*.parquet', 'README.md', 'SHA256SUMS.json']),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=SOURCES, required=True)
    parser.add_argument('--out', type=Path, default=Path('datasets/india-law/downloads'))
    args = parser.parse_args()
    from huggingface_hub import HfApi, snapshot_download
    repo, patterns = SOURCES[args.source]
    token = os.getenv('HF_TOKEN') or None
    dest = args.out / args.source
    dest.mkdir(parents=True, exist_ok=True)
    status_path = dest / 'download-status.json'
    status = {'repository': repo, 'complete': False, 'patterns': patterns}
    if status_path.exists():
        previous = json.loads(status_path.read_text())
        status['revision'] = previous.get('revision')
    try:
        info = HfApi(token=token).dataset_info(repo, revision=status.get('revision'))
        status['revision'] = info.sha
        status_path.write_text(json.dumps(status, indent=2))
        print(f"Downloading {repo} at {info.sha} to {dest}", flush=True)
        snapshot_download(repo, repo_type='dataset', revision=info.sha,
                          allow_patterns=patterns, local_dir=dest, token=token, max_workers=2)
        files = sorted(dest.rglob('*.parquet'))
        if not files:
            raise RuntimeError('No Parquet files downloaded.')
        status.update(complete=True, parquet_files=len(files), bytes=sum(p.stat().st_size for p in files))
    except Exception as exc:
        # Avoid provider exceptions potentially containing request credentials.
        status.update(error_type=type(exc).__name__)
        status_path.write_text(json.dumps(status, indent=2))
        raise SystemExit(f'Download incomplete ({type(exc).__name__}). Check dataset access/network and rerun to resume.')
    status_path.write_text(json.dumps(status, indent=2))
    print(json.dumps(status, indent=2), flush=True)


if __name__ == '__main__':
    main()
