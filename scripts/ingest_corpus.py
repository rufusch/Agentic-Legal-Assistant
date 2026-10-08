"""Resumable JSONL corpus importer. Default is validation-only; credentials stay in env.

python -m scripts.ingest_corpus manifest.jsonl --base-url https://backend.example --execute
Each row: {path, metadata:{corpus_id, corpus_version, document_type, jurisdiction, ...}}
This populates retrieval sources, never automatically approves model-training examples.
"""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import time
from urllib.parse import urlparse
import httpx

def rows(path):
    with path.open(encoding='utf-8-sig') as stream:
        for line_number,line in enumerate(stream,1):
            if not line.strip():continue
            item=json.loads(line);file=(path.parent/item['path']).resolve();meta=item['metadata']
            if not file.is_file() or not 0<file.stat().st_size<=25*1024*1024:raise ValueError(f'Row {line_number}: source missing or exceeds 25 MB')
            if meta.get('document_type') not in {'statute','judgment','case','contract','secondary','past_draft','user_input'}:raise ValueError(f'Row {line_number}: invalid document_type')
            if not all(meta.get(k) for k in ('corpus_id','corpus_version','jurisdiction')):raise ValueError(f'Row {line_number}: corpus_id, corpus_version and jurisdiction required')
            if len(json.dumps(meta).encode())>16000:raise ValueError(f'Row {line_number}: metadata too large')
            digest=hashlib.sha256()
            with file.open('rb') as source:
                for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
            key=hashlib.sha256((digest.hexdigest()+json.dumps(meta,sort_keys=True)).encode()).hexdigest()
            if item.get('sha256') and digest.hexdigest()!=item['sha256']:
                raise ValueError(f'Row {line_number}: source SHA256 does not match the manifest')
            yield file,meta,digest.hexdigest(),key

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path);parser.add_argument('--base-url',default='http://127.0.0.1:8000');parser.add_argument('--execute',action='store_true');parser.add_argument('--ledger',type=Path);parser.add_argument('--wait-seconds',type=int,default=180)
    args=parser.parse_args();url=urlparse(args.base_url)
    if url.scheme!='https' and not(url.scheme=='http' and url.hostname in {'localhost','127.0.0.1','::1'}):raise ValueError('Use HTTPS for remote servers')
    if url.username or url.password or url.query or url.fragment:raise ValueError('Credentials belong in CORPUS_API_TOKEN, not URLs')
    ledger=args.ledger or args.manifest.with_suffix('.import-ledger.jsonl')
    completed={}
    if ledger.exists():
        for line in ledger.read_text(encoding='utf-8').splitlines():
            item=json.loads(line);completed[item['key']]=item
    token=os.getenv('CORPUS_API_TOKEN')
    if args.execute and not token:raise ValueError('Set CORPUS_API_TOKEN before importing')
    total=0
    with httpx.Client(base_url=args.base_url.rstrip('/')+'/api/v1/',headers={'Authorization':'Bearer '+(token or '')},timeout=90,follow_redirects=False,trust_env=False) as client:
        def api(method,path,**kwargs):
            response=client.request(method,path,**kwargs);response.raise_for_status();return response.json()['data']
        for file,meta,sha,key in rows(args.manifest):
            total+=1
            if not args.execute:continue
            previous=completed.get(key)
            if previous:
                response=client.get('documents/'+previous['document_id'])
                if response.status_code==200 and response.json()['data']['status']=='ready':continue
                if response.status_code not in {200,404}:response.raise_for_status()
            media=mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            headers={'Idempotency-Key':'corpus-upload-'+key}
            ticket=api('POST','documents/uploads',json={'file_name':file.name,'content_type':media,'size_bytes':file.stat().st_size,'sha256':sha},headers=headers)
            doc=api('GET','documents/'+ticket['document_id'])
            if doc['status']=='uploading':
                if not doc.get('uploaded'):
                    with file.open('rb') as stream:
                        response=client.put(ticket['upload_url'],content=iter(lambda:stream.read(1024*1024),b''),headers={'Content-Type':media});response.raise_for_status()
                api('POST','documents/'+ticket['document_id']+'/complete',json={'upload_id':ticket['upload_id'],'metadata':meta},headers={'Idempotency-Key':'corpus-complete-'+key})
            elif doc['status']=='failed':api('POST','documents/'+doc['id']+'/retry')
            until=time.monotonic()+args.wait_seconds
            while time.monotonic()<until:
                doc=api('GET','documents/'+ticket['document_id'])
                if doc['status'] in {'ready','failed'}:break
                time.sleep(1)
            if doc['status']!='ready':raise RuntimeError('Import paused on non-ready document '+ticket['document_id']+'; resolve processing and rerun')
            entry={'key':key,'document_id':doc['id'],'sha256':sha,'corpus_id':meta['corpus_id'],'corpus_version':meta['corpus_version']}
            with ledger.open('a',encoding='utf-8') as stream:stream.write(json.dumps(entry)+'\n')
            completed[key]=entry
    print(f'{total} source rows validated; '+('import completed.' if args.execute else 'no uploads performed.'))

if __name__=='__main__':main()
