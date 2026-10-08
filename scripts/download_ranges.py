"""Resumable, hash-checked public large-file download using bounded range requests."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from pathlib import Path
import re
import time
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True)
    p.add_argument('--size', type=int, required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--workers', type=int, default=4)
    args = p.parse_args()
    if args.size <= 0 or args.workers <= 0 or not re.fullmatch(r'[0-9a-f]{64}', args.sha256):
        p.error('Positive size/workers and a lowercase SHA-256 digest are required.')
    parts = args.out.with_suffix(args.out.suffix + '.parts')
    parts.mkdir(parents=True, exist_ok=True)
    block_size = 8 * 1024 * 1024
    blocks = (args.size + block_size - 1) // block_size
    def fetch(index):
        start = index * block_size
        end = min(args.size, start + block_size) - 1
        dest = parts / f'{index:05}.part'
        if dest.exists() and dest.stat().st_size == end - start + 1:
            return
        for attempt in range(8):
            try:
                separator = '&' if '?' in args.url else '?'
                url = args.url + separator + f'case_lens_part={index}'
                request = urllib.request.Request(url, headers={'Range': f'bytes={start}-{end}'})
                with urllib.request.urlopen(request, timeout=90) as response:
                    if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{args.size}':
                        raise RuntimeError('Server did not honor requested byte range.')
                    data = response.read(end - start + 2)
                if len(data) != end - start + 1:
                    raise RuntimeError('Incomplete byte range.')
                dest.write_bytes(data)
                return
            except Exception:
                if attempt == 7:
                    raise RuntimeError(f'Range {index} failed after bounded retries.') from None
                time.sleep(min(30, 2 ** attempt))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for completed, future in enumerate(as_completed([pool.submit(fetch, index) for index in range(blocks)]), 1):
            future.result()
            if completed % 10 == 0 or completed == blocks:
                print(f'{args.out.name}: {completed}/{blocks} ranges complete', flush=True)
    digest = hashlib.sha256()
    temporary = args.out.with_suffix(args.out.suffix + '.assembling')
    with temporary.open('wb') as output:
        for index in range(blocks):
            with (parts / f'{index:05}.part').open('rb') as source:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk); digest.update(chunk)
    if digest.hexdigest() != args.sha256:
        raise SystemExit('SHA-256 mismatch: completed file was not published.')
    temporary.replace(args.out)
    print(f'{args.out.name}: complete, SHA-256 verified', flush=True)


if __name__ == '__main__':
    main()
