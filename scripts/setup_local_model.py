"""Fetch official portable Ollama; --gpu adds NVIDIA CUDA 12 libraries."""
import io
import json
import os
from pathlib import Path
import subprocess
import time
import zlib
import zipfile

import httpx


class RemoteZip(io.RawIOBase):
    def __init__(self, client, url, size):
        self.client, self.url, self.size, self.position = client, url, size, 0
        self.cache, self.cache_start = b'', 0

    def seekable(self): return True
    def tell(self): return self.position
    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        return self.position

    def read(self, size=-1):
        if self.position >= self.size: return b''
        end = self.size-1 if size < 0 else min(self.size-1,self.position+size-1)
        if self.cache_start <= self.position and end < self.cache_start+len(self.cache):
            content=self.cache[self.position-self.cache_start:end-self.cache_start+1]
        else:
            fetch_end=min(self.size-1,max(end,self.position+4*1024*1024-1))
            for attempt in range(5):
                try:
                    with self.client.stream('GET', self.url, headers={'Range':f'bytes={self.position}-{fetch_end}'}) as response:
                        if response.status_code != 206: raise RuntimeError('Official server did not support bounded range download.')
                        self.url=str(response.url)
                        self.cache=response.read()
                    break
                except httpx.HTTPError:
                    if attempt==4:raise
                    time.sleep(1+attempt)
            self.cache_start=self.position
            content=self.cache[:end-self.position+1]
        self.position += len(content)
        return content


def main():
    root = Path(__file__).resolve().parent.parent
    destination = root / '.runtime' / 'ollama'
    destination.mkdir(parents=True,exist_ok=True)
    with httpx.Client(follow_redirects=True,timeout=120) as client:
        release = client.get('https://api.github.com/repos/ollama/ollama/releases/latest').raise_for_status().json()
        asset = next(a for a in release['assets'] if a['name']=='ollama-windows-amd64.zip')
        with zipfile.ZipFile(RemoteZip(client,asset['browser_download_url'],asset['size'])) as archive:
            names = [i.filename for i in archive.infolist()]
            if '--list' in __import__('sys').argv:
                print(json.dumps(names));return
            gpu = '--gpu' in __import__('sys').argv
            selected = [i for i in archive.infolist() if not i.is_dir() and (i.filename=='ollama.exe' or (i.filename.startswith('lib/ollama/') and (not any(p in i.filename.lower() for p in ['cuda','vulkan','rocm','mlx']) or (gpu and i.filename.startswith('lib/ollama/cuda_v12/')))))]
            for item in selected:
                target = (destination / item.filename).resolve()
                if not target.is_relative_to(destination.resolve()): raise RuntimeError('Unexpected archive path')
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists() and target.stat().st_size==item.file_size and zlib.crc32(target.read_bytes())==item.CRC: continue
                with archive.open(item) as source, target.open('wb') as output:
                    while block := source.read(1024*1024): output.write(block)
                print(json.dumps({'file':item.filename,'bytes':item.file_size}),flush=True)
    (destination/'version.json').write_text(json.dumps({'version':release['tag_name'],'source':asset['browser_download_url']}))


if __name__=='__main__': main()
