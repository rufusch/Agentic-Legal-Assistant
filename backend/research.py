"""Legal Research API with tenant-scoped retrieval and durable jobs."""
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
from typing import Literal
from uuid import UUID, uuid4
from fastapi import Request
from fastapi.responses import Response
from backend.jobs import TERMINAL
from backend.models.review_llm import LocalReviewLLM, ReviewCancelled, ReviewModelError
from backend.research_schema import CreateResearch, RefineResearch, ResearchFeedback, ResearchMemo
from backend.research_engine import synthesize
from backend.retrieval import search

def uid(): return str(uuid4())
def now(): return datetime.now(timezone.utc).isoformat()

def training_dataset(store,tenant):
    latest={}
    for f in sorted(store.all(tenant,'research_feedback'),key=lambda f:f['created_at']): latest[f['research_id']]=f
    rows=[]
    for candidate in store.all(tenant,'research_training'):
        f=latest.get(candidate['research_id'])
        if f and f['accepted'] and f['use_for_training']:
            rows.append({k:v for k,v in candidate.items() if k not in {'id','created_at'}})
    return rows

def install(app,store,worker,get,envelope,APIError,idempotent,research_llm=None):
    def env(key,fallback):return os.getenv('LEXIMIND_RESEARCH_'+key,fallback)
    llm = research_llm or LocalReviewLLM.for_role('research')
    app.state.research_llm=llm
    def metadata():return {**llm.metadata,'id':'leximind-research','workflow':'research','output_schema':'research-memo-v1','prompt_version':'grounded-research-v1'}

    def retrieve(tenant,memo):
        docs={d['id']:d for d in store.all(tenant,'document') if d['status']=='ready'}
        selected=set(memo['context_document_ids']);filters=memo['filters'];options=memo['options']
        if not selected<=docs.keys(): raise ReviewModelError('SOURCES_NOT_READY','A selected context source is unavailable.',False)
        authorities=set();excluded=0
        for rid,doc in docs.items():
            m=doc['metadata'];kind=m.get('document_type')
            if kind not in filters['source_types'] or kind=='secondary' and not options['include_secondary_sources']:continue
            if filters['jurisdictions'] and m.get('jurisdiction') not in filters['jurisdictions']:excluded+=1;continue
            if filters['courts'] and kind=='judgment' and m.get('court') not in filters['courts']:excluded+=1;continue
            date=m.get('decided_at') if kind=='judgment' else m.get('effective_from')
            if filters['date_from'] or filters['date_to']:
                try:
                    from datetime import date as Date
                    date=Date.fromisoformat(str(date))
                    if filters['date_from'] and date<Date.fromisoformat(filters['date_from']) or filters['date_to'] and date>Date.fromisoformat(filters['date_to']):excluded+=1;continue
                except (ValueError,TypeError):excluded+=1;continue
            authorities.add(rid)
        all_chunks=store.all(tenant,'chunk');chosen=[];used=0;logs=[]
        for label,ids in [('Governing statutes',{i for i in authorities if docs[i]['metadata'].get('document_type')=='statute'}),('Precedents',{i for i in authorities if docs[i]['metadata'].get('document_type')=='judgment'}),('Secondary commentary',{i for i in authorities if docs[i]['metadata'].get('document_type')=='secondary'}),('Case context',selected-authorities)]:
            # Context cannot bypass authority filters through a selected-file checkbox.
            ids={i for i in ids if i in authorities or docs[i]['metadata'].get('document_type') not in {'statute','judgment','secondary','past_draft'}}
            pool=[c for c in all_chunks if c['document_id'] in ids]
            hits=search(pool,memo['question'],12 if options['depth']=='deep' else 6)
            included=[]
            for c in hits:
                if used+len(c['text'])<=24000 and c['id'] not in {v['id'] for v in chosen}:chosen.append(c);used+=len(c['text']);included.append(c['id'])
            logs.append({'id':uid(),'question':label+': '+memo['question'],'status':'completed' if included else 'limited_evidence','filters':filters,'candidate_chunks':len(pool),'retrieved_chunk_ids':included,'source_document_ids':sorted(ids)})
        memo['source_document_ids']=sorted(selected|{c['document_id'] for c in chosen})
        memo['search_log']=logs;memo['sub_queries']=[{k:entry[k] for k in ('id','question','status')} for entry in logs]
        memo['retrieval']={'context_characters':used,'excluded_by_filters':excluded,'method':'bm25-lsa-rrf-v1','maximum_context_characters':24000}
        return [docs[i] for i in {c['document_id'] for c in chosen}],chosen

    def execute(tenant,rid,jid):
        memo=get(tenant,'research',rid);job=get(tenant,'job',jid)
        try:
            def progress(stage,value,message):
                with store.transaction():
                    if worker.cancelled(tenant,jid):raise ReviewCancelled()
                    memo['status']=stage;job.update(status=stage,progress=value)
                    store.save(tenant,'research',memo);store.save(tenant,'job',job);store.event(jid,'job.progress',status=stage,progress=value,message=message)
            progress('retrieving',.1,'Searching workspace authorities and selected case context')
            documents,chunks=retrieve(tenant,memo)
            memo=synthesize(memo,documents,chunks,llm,lambda:worker.cancelled(tenant,jid),progress)
            with store.transaction():
                if worker.cancelled(tenant,jid):return
                candidate=memo.pop('training_candidate',None)
                memo=ResearchMemo.model_validate(memo).model_dump(mode='json')
                if candidate and memo['claims']:
                    store.save(tenant,'research_training',{'id':uid(),'research_id':rid,'workflow':'research','model_id':'leximind-research','model_version':memo['model']['version'],'source_document_ids':memo['source_document_ids'],'source_hashes':sorted(d['sha256'] for d in documents),'created_at':now(),'messages':candidate['messages']+[{'role':'assistant','content':json.dumps(candidate['target'],ensure_ascii=False)}]})
                store.save(tenant,'research',memo)
                job.update(status=memo['status'],progress=1,result_id=rid,warnings=memo['warnings']);store.save(tenant,'job',job)
                store.event(jid,'job.completed',status=job['status'],result_id=rid);store.db.execute('DELETE FROM queue WHERE job=?',(jid,))
                store.audit(tenant,'research.completed',rid,model=memo['model'])
        except ReviewCancelled:return
        except Exception as exc:
            with store.transaction():
                if worker.cancelled(tenant,jid):return
                failure={'code':exc.code,'message':exc.message,'retryable':exc.retryable} if isinstance(exc,ReviewModelError) else {'code':'RESEARCH_VERIFICATION_FAILED','message':'Research failed source verification; no unchecked memo was published.','retryable':True}
                memo.pop('training_candidate',None);memo.update(status='failed',failure=failure,claims=[],citations=[],legal_framework=[],application_to_facts=[],executive_summary={'text':'Research did not pass verification.','claim_ids':[],'citation_ids':[]})
                job.update(status='failed',failure=failure);store.save(tenant,'research',memo);store.save(tenant,'job',job)
                store.event(jid,'job.failed',**failure);store.db.execute('DELETE FROM queue WHERE job=?',(jid,))
    worker.handlers['research']=execute

    def submit(tenant,body,parent=None):
        if sum(j['status'] not in TERMINAL for j in store.all(tenant,'job'))>=20:raise APIError(429,'QUEUE_FULL','Wait for queued jobs.',True)
        for rid in body.context_document_ids:
            if get(tenant,'document',rid)['status']!='ready':raise APIError(409,'DOCUMENT_NOT_READY','Wait for selected documents to finish parsing.')
        rid=uid();jid=uid();payload=body.model_dump(mode='json')
        memo={'id':rid,**payload,'status':'queued','parent_id':parent,'version':1,'created_at':now(),'model':metadata(),'source_document_ids':payload['context_document_ids'],'job_id':jid,'failure':None,'scope':{'interpreted_question':body.question,'assumptions':['Jurisdiction is unrestricted unless filters are provided.'],'jurisdictions':body.filters.jurisdictions,'as_of_date':now()[:10]},'claims':[],'citations':[],'warnings':[],'search_log':[],'sub_queries':[]}
        job={'id':jid,'workflow':'research','resource_id':rid,'status':'queued','progress':0,'created_at':now(),'result_id':None,'warnings':[],'failure':None}
        store.save(tenant,'research',memo);store.save(tenant,'job',job);store.db.execute('INSERT INTO queue VALUES(?,?,?,?)',(jid,tenant,rid,'queued'))
        store.event(jid,'job.progress',status='queued',progress=0,message='Legal Research queued');worker.wake.set()
        return {'research_id':rid,'job_id':jid,'status':'queued','events_url':f'/api/v1/jobs/{jid}/events'}

    @app.post('/api/v1/research',status_code=202)
    def create(request:Request,body:CreateResearch):
        def build():
            with store.transaction():return envelope(request,submit(request.state.tenant,body))
        return idempotent(request,body.model_dump(mode='json'),build)

    @app.get('/api/v1/research')
    def listing(request:Request):return envelope(request,{'items':sorted(store.all(request.state.tenant,'research'),key=lambda m:m['created_at'],reverse=True)[:100]})
    @app.get('/api/v1/research/config')
    def config(request:Request):return envelope(request,{**llm.status(),'model':metadata(),'external_legal_database':False})
    @app.get('/api/v1/research/{rid}')
    def read(rid:UUID,request:Request):return envelope(request,get(request.state.tenant,'research',rid))
    @app.get('/api/v1/research/{rid}/search-log')
    def log(rid:UUID,request:Request):return envelope(request,{'items':get(request.state.tenant,'research',rid)['search_log']})
    @app.post('/api/v1/research/{rid}/refine',status_code=202)
    def refine(rid:UUID,request:Request,body:RefineResearch):
        def build():
            with store.transaction():
                old=get(request.state.tenant,'research',rid)
                if old['status'] not in {'completed','completed_with_warnings'}:raise APIError(409,'RESEARCH_NOT_READY','Complete the original memo first.')
                payload={k:old[k] for k in ('question','context_document_ids','filters','options')};payload['question']+='\nRefinement: '+body.instruction
                if len(payload['question'])>4000:raise APIError(400,'VALIDATION_ERROR','Refined question exceeds 4,000 characters.')
                return envelope(request,submit(request.state.tenant,CreateResearch.model_validate(payload),str(rid)))
        return idempotent(request,body.model_dump(),build)
    @app.post('/api/v1/research/{rid}/feedback')
    def feedback(rid:UUID,request:Request,body:ResearchFeedback):
        with store.transaction():
            memo=get(request.state.tenant,'research',rid)
            if memo['status'] not in {'completed','completed_with_warnings'}:raise APIError(409,'RESEARCH_NOT_READY','Complete the memo before approval.')
            item={'id':uid(),'research_id':str(rid),'created_at':now(),'source_document_ids':memo['source_document_ids'],**body.model_dump()};store.save(request.state.tenant,'research_feedback',item)
            return envelope(request,{'feedback_id':item['id'],'training_eligible':bool(memo['claims']) and body.accepted and body.use_for_training})
    @app.get('/api/v1/research/{rid}/export')
    def export(rid:UUID,request:Request,format:Literal['json','docx','pdf']='json'):
        memo=get(request.state.tenant,'research',rid)
        if memo['status'] not in {'completed','completed_with_warnings'}:raise APIError(409,'RESEARCH_NOT_READY','Complete the memo before export.')
        if format=='json':data=json.dumps(memo,ensure_ascii=False).encode();media='application/json'
        else:
            lines=['Legal Research — working memo',memo['question'],memo['executive_summary']['text'],*[c['text'] for c in memo['claims']],*['LIMITATION: '+v for v in memo['limitations']],*[f'[{c["label"]}] {c["document_name"]}: {c["quoted_text"]}' for c in memo['citations']]];stream=BytesIO()
            if format=='docx':
                from docx import Document
                doc=Document()
                for line in lines:doc.add_paragraph(line)
                doc.save(stream);media='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            else:
                from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
                from reportlab.lib.styles import getSampleStyleSheet
                from xml.sax.saxutils import escape
                styles=getSampleStyleSheet();story=[]
                for line in lines:story.extend([Paragraph(escape(line),styles['BodyText']),Spacer(1,8)])
                SimpleDocTemplate(stream).build(story);media='application/pdf'
            data=stream.getvalue()
        return Response(data,media_type=media,headers={'Content-Disposition':f'attachment; filename="legal-research.{format}"'})
