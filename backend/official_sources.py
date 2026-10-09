"""Fetch bounded official PDFs, index exact spans per tenant, and preserve provenance.

The catalog is discovery metadata, never evidence. Only successfully parsed official
PDF bytes (or hash-verified dated starter snapshots) enter model evidence packets.
"""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import time
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import httpx
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from backend.parsing import chunks
from backend.retrieval import terms

ROOT = Path(__file__).resolve().parents[1]
HOSTS = {'indiacode.nic.in','www.indiacode.nic.in','indiacode.gov.in','www.indiacode.gov.in',
         'sci.gov.in','www.sci.gov.in','api.sci.gov.in','main.sci.gov.in','scr.sci.gov.in',
         'judgments.ecourts.gov.in','legislative.gov.in','www.legislative.gov.in',
         'lddashboard.legislative.gov.in','eparlib.sansad.in','www.mha.gov.in','mha.gov.in',
         'delhihighcourt.nic.in','www.delhihighcourt.nic.in','bombayhighcourt.nic.in',
         'www.bombayhighcourt.nic.in','highcourtofkerala.nic.in','www.highcourtofkerala.nic.in',
         'cdnbbsr.s3waas.gov.in'}
MAX_BYTES = 25 * 1024 * 1024
TTL = 24 * 3600


class OfficialSourceError(Exception): pass


def validate_url(url, resolve=False):
    p = urlsplit(url)
    try: port = p.port
    except ValueError: raise OfficialSourceError('Invalid official URL.')
    if p.scheme != 'https' or p.hostname not in HOSTS or p.username or p.password or p.fragment or port not in (None,443):
        raise OfficialSourceError('Use an HTTPS URL on a supported official government or court website.')
    if resolve:
        try:
            addresses = socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
        except OSError: raise OfficialSourceError('Official website DNS is unavailable.')
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise OfficialSourceError('Official website resolved to a non-public address.')
    return url


class Links(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            href=dict(attrs).get('href','')
            if '.pdf' in href.lower(): self.links.append(href)


def fetch(url, deadline=None):
    deadline = deadline or time.monotonic()+20
    # Redirects are checked separately; no credentials/cookies from the application.
    with httpx.Client(timeout=httpx.Timeout(8,connect=5),follow_redirects=False,trust_env=False,
                      headers={'User-Agent':'CaseLens/1.0 official-source-reader','Accept':'application/pdf,text/html'}) as client:
        for _ in range(5):
            validate_url(url,resolve=True)
            if time.monotonic()>deadline:raise OfficialSourceError('Official source retrieval timed out.')
            with client.stream('GET',url) as r:
                if r.status_code in {301,302,303,307,308}:
                    url=urljoin(url,r.headers.get('location',''));continue
                if r.status_code!=200:raise OfficialSourceError(f'Official website returned HTTP {r.status_code}; no source imported.')
                raw=bytearray()
                for piece in r.iter_bytes(65536):
                    if len(raw)+len(piece)>MAX_BYTES:raise OfficialSourceError('Official PDF exceeds the 25 MB limit.')
                    if time.monotonic()>deadline:raise OfficialSourceError('Official source retrieval timed out.')
                    raw.extend(piece)
                raw=bytes(raw)
                if raw.lstrip().startswith(b'%PDF-'):return raw,url
                if urlsplit(url).hostname not in {'www.indiacode.nic.in','indiacode.nic.in','www.indiacode.gov.in','indiacode.gov.in'}:
                    raise OfficialSourceError('This official page is not a PDF. Copy the judgment or statute PDF link; CAPTCHA pages are not imported.')
                parser=Links();parser.feed(raw.decode('utf-8','replace'))
                candidates=[urljoin(url,link) for link in parser.links]
                # Match the exact India Code record, never a footer/privacy/related Act PDF.
                match=re.search(r'/handle/(123456789/[^/?]+)',urlsplit(url).path)
                candidates=[u for u in candidates if match and '/bitstream/'+match.group(1)+'/' in u]
                valid=[]
                for candidate in candidates:
                    try:validate_url(candidate);valid.append(candidate)
                    except OfficialSourceError:pass
                if not valid:raise OfficialSourceError('No accessible official PDF found; CAPTCHA or HTML-only source is not evidence.')
                url=valid[0]
    raise OfficialSourceError('Too many official redirects or landing pages.')


def catalog():
    path=ROOT/'corpus'/'official-catalog.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


class OfficialSources:
    def __init__(self,store,worker,retention_days=30):
        self.store,self.worker,self.retention=store,worker,retention_days
        self.enabled=os.getenv('LEXIMIND_OFFICIAL_SOURCES','1')=='1'

    def discover(self,question,limit=4):
        query=set(terms(question))-{'act','law','laws','legal','section','case','court','india','indian','judgment','judgement','does','what','which'};ranked=[];seen=set()
        for item in catalog():
            if item['url'] in seen:continue
            seen.add(item['url'])
            tags=set(terms(item['title']+' '+item.get('keywords','')))
            score=len(query&tags)
            if score:ranked.append((score,item))
        ranked.sort(key=lambda v:(-v[0],v[1]['title']))
        return [item for _,item in ranked[:limit]]

    def import_source(self,tenant,url,title,kind,cancelled=lambda:False):
        validate_url(url)
        if cancelled():raise OfficialSourceError('Official source import cancelled.')
        stamp=time.time()
        old=next((d for d in self.store.all(tenant,'document') if d['status']=='ready'
                  and self.verified(tenant,d) and d['metadata'].get('requested_url')==url
                  and stamp-d['metadata'].get('fetched_timestamp',0)<TTL),None)
        if old:return old
        retrieval_mode='live_official_pdf';snapshot_date=None;live_error=None
        try: raw,final_url=fetch(url)
        except Exception as exc:
            live_error=str(exc) if isinstance(exc,OfficialSourceError) else 'Official website unavailable or timed out.'
            # Only the exact URL, recorded hash and dated official snapshot qualify.
            manifest=ROOT/'corpus'/'public-starter'/'manifest.jsonl'
            entry=next((json.loads(line) for line in manifest.read_text().splitlines()
                        if json.loads(line)['metadata']['source_url']==url),None) if manifest.exists() else None
            if not entry:raise OfficialSourceError(live_error)
            raw=(manifest.parent/entry['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise OfficialSourceError('Official snapshot integrity check failed.')
            final_url=url;retrieval_mode='dated_official_snapshot';snapshot_date=entry['metadata']['retrieved_at']
        parsed=self.worker.parser(raw,'application/pdf',cancelled)
        if cancelled() or parsed.get('cancelled'):raise OfficialSourceError('Official source import cancelled.')
        if parsed.get('failure'):raise OfficialSourceError(parsed['failure']['message'])
        parsed=parsed.get('result',{})
        if not parsed.get('pages') or not any(p['text'].strip() for p in parsed['pages']):raise OfficialSourceError('No readable official source text.')
        rid=str(uuid4());now=datetime.now(timezone.utc).isoformat()
        metadata={'title':title,'document_type':kind,'jurisdiction':'IN','source_url':final_url,
                  'requested_url':url,'official_verified':True,'retrieved_at':now,'fetched_timestamp':stamp,
                  'retrieval_mode':retrieval_mode,'snapshot_date':snapshot_date,'live_fetch_failure':live_error,
                  'currency_status':'not_certified','content_sha256':hashlib.sha256(raw).hexdigest()}
        if urlsplit(final_url).hostname in {'api.sci.gov.in','main.sci.gov.in','sci.gov.in','www.sci.gov.in','scr.sci.gov.in'}:
            metadata['court']='Supreme Court of India'
        doc={'id':rid,'name':title[:240]+'.pdf','status':'ready','media_type':'application/pdf','size_bytes':len(raw),
             'sha256':metadata['content_sha256'],'metadata':metadata,'created_at':now,'uploaded':True,
             'page_count':len(parsed['pages']),'ocr_used':any(p.get('ocr') for p in parsed['pages']),
             'warnings':[{'id':str(uuid4()),'type':w[0],'severity':w[1],'title':w[2],'message':w[3],'resolvable':False} for w in parsed.get('warnings',[])],
             'failure':None,'processing':{'stage':'indexed','progress':1},
             'retention_expires_at':stamp+self.retention*86400,'parser_version':parsed.get('parser_version','sources-v2')}
        entries=[]
        for page in parsed['pages']:
            for start,end,text in chunks(page['text']):
                entries.append({'id':str(uuid4()),'document_id':rid,'page':page['number'],'source_part':page['number'],
                                'section':None,'start_offset':start,'end_offset':end,'text':text,'terms':terms(text)})
        doc['chunk_count']=len(entries)
        if not entries:raise OfficialSourceError('No indexable official text.')
        with self.store.transaction():
            self.store.write_blob(rid,raw)
            self.store.save(tenant,'document',doc)
            self.store.save(tenant,'official_source_receipt',{'id':'official-'+rid,'document_id':rid,'sha256':doc['sha256'],'source_url':final_url})
            for item in entries:self.store.save(tenant,'chunk',item)
            self.store.audit(tenant,'official_source.imported',rid,source_url=final_url,sha256=doc['sha256'],retrieval_mode=retrieval_mode)
        return doc

    def verified(self,tenant,document):
        receipt=self.store.get(tenant,'official_source_receipt','official-'+document['id'])
        return bool(receipt and receipt['sha256']==document['sha256']
                    and receipt['source_url']==document['metadata'].get('source_url'))

    def current_documents(self,tenant):
        latest={}
        for d in self.store.all(tenant,'document'):
            if d['status']!='ready' or not self.verified(tenant,d):continue
            key=d['metadata'].get('requested_url',d['metadata']['source_url'])
            if key not in latest or d['metadata'].get('fetched_timestamp',0)>latest[key]['metadata'].get('fetched_timestamp',0):latest[key]=d
        return list(latest.values())

    def enrich(self,tenant,question,cancelled=lambda:False,document_types=None):
        result={'enabled':self.enabled,'discovery':'local catalog of official URLs; not an exhaustive court search',
                'sources':[],'failures':[],'currency_certified':False}
        if not self.enabled:return result
        for item in [i for i in self.discover(question,12) if document_types is None or i['document_type'] in document_types][:3]:
            if cancelled():break
            try:
                doc=self.import_source(tenant,item['url'],item['title'],item['document_type'],cancelled)
                result['sources'].append({'document_id':doc['id'],'url':doc['metadata']['source_url'],
                                          'retrieval_mode':doc['metadata']['retrieval_mode'],
                                          'snapshot_date':doc['metadata']['snapshot_date']})
            except Exception as exc:
                result['failures'].append({'url':item['url'],'message':str(exc) if isinstance(exc,OfficialSourceError) else 'Official source unavailable.'})
        return result


def citation_provenance(document):
    m=document.get('metadata',{})
    return {**{k:m.get(k) for k in ('source_url','jurisdiction','court','decided_at','retrieved_at','snapshot_date','retrieval_mode')},
            'source_sha256':document.get('sha256')}


def citation_source_text(citation):
    fields=[('source_url','Source'),('retrieved_at','Retrieved'),('snapshot_date','Dated snapshot'),('source_sha256','SHA-256')]
    return ''.join(f" | {label}: {citation[key]}" for key,label in fields if citation.get(key))


class ImportOfficial(BaseModel):
    model_config=ConfigDict(extra='forbid')
    url:str=Field(min_length=10,max_length=2000)
    title:str=Field(min_length=2,max_length=200)
    document_type:str=Field(pattern='^(statute|judgment)$')


def install(app,store,worker,envelope,APIError,retention_days):
    service=OfficialSources(store,worker,retention_days);app.state.official_sources=service
    @app.get('/api/v1/official-sources')
    def listing(request:Request,query:str=''):
        if len(query)>2000:raise APIError(400,'VALIDATION_ERROR','Query exceeds 2,000 characters.')
        return envelope(request,{'enabled':service.enabled,'items':service.discover(query,12) if query else catalog()[:12],
            'supported_hosts':sorted(HOSTS),'limitations':'Catalog search is limited. Official provenance does not certify current law or case treatment.'})
    @app.post('/api/v1/official-sources/import',status_code=201)
    def importing(request:Request,body:ImportOfficial):
        if not service.enabled:raise APIError(409,'OFFICIAL_SOURCES_DISABLED','Official source retrieval is disabled.')
        try:doc=service.import_source(request.state.tenant,body.url,body.title,body.document_type)
        except OfficialSourceError as exc:raise APIError(422,'OFFICIAL_SOURCE_UNAVAILABLE',str(exc),True)
        except Exception:raise APIError(502,'OFFICIAL_SOURCE_UNAVAILABLE','Official source unavailable; no unchecked source imported.',True)
        return envelope(request,{'document_id':doc['id'],'status':'ready','metadata':doc['metadata']})
