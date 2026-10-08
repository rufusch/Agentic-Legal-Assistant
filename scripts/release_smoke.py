"""Real-model release smoke test in an isolated workspace; no training or real case data."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import create_app


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workflows',default='chat,review,drafting,research')
    args=parser.parse_args();app=create_app(args.storage,{'release-smoke-only':'release-smoke'})
    results={'fixture':'Synthetic acceptance data; not legal authority.','started_at':time.time(),'workflows':{},'models':{}}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():args.output.write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer release-smoke-only'
        results['models']=c.get('/api/v1/models').json()['data'];save()
        def wait(jid):
            started=time.monotonic();last=None
            while time.monotonic()-started<2400:
                job=c.get('/api/v1/jobs/'+jid).json()['data']
                if job['status']!=last:print(jid,job['status'],flush=True);last=job['status']
                if job['status'] in {'completed','completed_with_warnings','failed','cancelled'}:return job
                time.sleep(2)
            c.post('/api/v1/jobs/'+jid+'/cancel');raise RuntimeError('Acceptance deadline exceeded')
        text=b'SYNTHETIC TEST CONTRACT. Example Buyer must pay Example Supplier INR 5000 within ten days of invoice.\n'
        source_hash=hashlib.sha256(text).hexdigest();results['source_sha256']=source_hash
        t=c.post('/api/v1/documents/uploads',json={'file_name':'release-contract.txt','content_type':'text/plain','size_bytes':len(text),'sha256':source_hash}).json()['data']
        c.put(t['upload_url'],content=text).raise_for_status()
        parsed=c.post('/api/v1/documents/'+t['document_id']+'/complete',json={'upload_id':t['upload_id'],'metadata':{'document_type':'contract','jurisdiction':'IN','title':'Synthetic release contract'}}).json()['data'];wait(parsed['job_id']);rid=t['document_id']
        for workflow in args.workflows.split(','):
            started=time.monotonic()
            if workflow=='chat':
                cid=c.post('/api/v1/conversations',json={'title':'Release smoke','document_ids':[rid]}).json()['data']['conversation_id']
                ticket=c.post(f'/api/v1/conversations/{cid}/messages',json={'content':'Who must pay whom? Return one concise supported statement only.','selected_document_ids':[rid]}).json()['data']
                job=wait(ticket['job_id']);result=next(m for m in c.get(f'/api/v1/conversations/{cid}/messages').json()['data'] if m['id']==ticket['assistant_message_id'])
            elif workflow=='review':
                ticket=c.post('/api/v1/reviews',json={'document_ids':[rid],'focus_question':'Identify the payment obligation. Keep one key fact, one evidence item and one overview. Leave all other lists empty unless necessary.'}).json()['data'];job=wait(ticket['job_id']);result=c.get('/api/v1/reviews/'+ticket['review_id']).json()['data']
            elif workflow=='drafting':
                payload={'document_type':'contract_clause','jurisdiction':'IN','instructions':'Write one short payment clause with one section and one paragraph only. No background, grounds, relief, verification, signature, schedule or notice sections. Use only the supplied facts.','facts':{'parties':'Example Buyer and Example Supplier','clause_purpose':'Payment','obligations':'Example Buyer must pay Example Supplier INR 5000 within ten days of invoice.','effective_date':'When an invoice is issued.'},'supporting_document_ids':[rid]}
                ticket=c.post('/api/v1/drafts',json=payload).json()['data'];wait(ticket['job_id']);did=ticket['draft_id']
                ticket=c.post('/api/v1/drafts/'+did+'/generate',json={'proceed_with_missing_information':False}).json()['data'];job=wait(ticket['job_id']);result=c.get('/api/v1/drafts/'+did).json()['data']
            elif workflow=='research':
                # Contract evidence must never masquerade as governing authority.
                ticket=c.post('/api/v1/research',json={'question':'What statute certifies enforceability of this synthetic contract?','context_document_ids':[rid]}).json()['data'];job=wait(ticket['job_id']);result=c.get('/api/v1/research/'+ticket['research_id']).json()['data']
            else:raise ValueError(workflow)
            from backend.evidence import EvidenceBundle
            if job['status'] in {'completed','completed_with_warnings'}:
                bundle=EvidenceBundle.model_validate(result)
                bundle.validate_source_spans(lambda d,ch:c.get(f'/api/v1/documents/{d}/chunks/{ch}').json()['data'])
            results['workflows'][workflow]={'elapsed_seconds':round(time.monotonic()-started,2),'job':job,'result':result};save()
            print(workflow,job['status'],'claims',len(result.get('claims',[])),flush=True)
    app.state.store.close();results['finished_at']=time.time();save()


if __name__=='__main__':main()
