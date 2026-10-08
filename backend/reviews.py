import json
import time
import os
from io import BytesIO
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import Response
from backend.models import ModelRegistry
from backend.review_schema import CreateReview, RerunReview, verify_report
from backend.review_engine import generate, confidence
from backend.jobs import TERMINAL
from backend.models.review_llm import LocalReviewLLM, ReviewModelError, ReviewCancelled
from backend.llm_review_engine import analyze, MAX_SOURCE_CHARACTERS


class Annotation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chunk_id: UUID
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    label: str = Field(max_length=100)


class Feedback(BaseModel):
    model_config = ConfigDict(extra='forbid')
    accepted: bool
    use_for_training: bool = False
    annotations: list[Annotation] = Field(default_factory=list, max_length=100)


def install(app, store, worker, get, envelope, APIError, idempotent, *, review_engine=None, review_llm=None, verify_llm=None):
    models = ModelRegistry()
    app.state.models = models
    engine=review_engine or os.getenv('LEXIMIND_REVIEW_ENGINE','llm')
    if engine not in {'llm','extractive'}: raise ValueError('Invalid review engine')
    llm=review_llm or LocalReviewLLM.for_role('review')
    from backend.agent_loop import verifier
    checker=verifier(llm, verify_llm)
    app.state.review_llm, app.state.review_engine, app.state.review_verify_llm = llm, engine, checker

    def model_metadata(): return llm.metadata if engine=='llm' else models.get('review').metadata

    def execute(tenant, resource, job_id):
        report = get(tenant, 'review', resource)
        job = get(tenant, 'job', job_id)
        try:
            def update_progress(stage, progress, message):
                with store.transaction():
                    if worker.cancelled(tenant, job_id): raise ReviewCancelled()
                    job.update(status=stage, progress=progress)
                    report['status']=stage
                    store.save(tenant,'review',report)
                    store.save(tenant, 'job', job)
                    store.event(job_id, 'job.progress', status=stage, progress=progress, message=message)
            update_progress('understanding',.05,'Loading parsed document evidence')
            documents = [get(tenant, 'document', rid) for rid in report['source_document_ids']]
            chunks = [c for c in store.all(tenant, 'chunk') if c['document_id'] in report['source_document_ids']]
            requested_version=report['model']['version']
            if engine=='llm':
                result=analyze(report,documents,chunks,llm,lambda:worker.cancelled(tenant,job_id),update_progress,verify_llm=checker)
            else:
                report['model']={**model_metadata(),'requested_version':requested_version}
                result = generate(report, documents, chunks, models.get('review'), lambda: worker.cancelled(tenant, job_id))
            if result is None: return
            result = verify_report(result, chunks)
            with store.transaction():
                if worker.cancelled(tenant, job_id): return
                store.save(tenant, 'review', result)
                job.update(status=result['status'], progress=1, result_id=resource)
                job['warnings']=result['warnings']
                store.save(tenant, 'job', job)
                store.event(job_id, 'job.completed', status=job['status'], result_id=resource)
                store.db.execute('DELETE FROM queue WHERE job=?', (job_id,))
                store.audit(tenant, 'review.completed', resource, model=result['model'])
        except ReviewCancelled: return
        except Exception as exc:
            with store.transaction():
                if worker.cancelled(tenant, job_id): return
                failure = {'code':exc.code,'message':exc.message,'retryable':exc.retryable} if isinstance(exc,ReviewModelError) else {'code':'REVIEW_VERIFICATION_FAILED','message':'Review could not pass source verification. Retry with ready sources.','retryable':True}
                report.update(status='failed', failure=failure)
                job.update(status='failed', failure=failure)
                store.save(tenant, 'review', report)
                store.save(tenant, 'job', job)
                store.event(job_id, 'job.failed', **failure)
                store.db.execute('DELETE FROM queue WHERE job=?', (job_id,))

    worker.handlers = {'review': execute}

    def create(request, body, previous=None):
        tenant = request.state.tenant
        with store.transaction():
            ids = list(dict.fromkeys(map(str, [*body.document_ids, *body.options.authority_document_ids])))
            for rid in ids:
                doc = get(tenant, 'document', rid)
                if doc['status'] != 'ready': raise APIError(409, 'SOURCES_NOT_READY', 'Every selected source must be ready.')
            if engine=='llm' and sum(len(c['text']) for c in store.all(tenant,'chunk') if c['document_id'] in ids)>MAX_SOURCE_CHARACTERS:
                raise APIError(413,'REVIEW_CONTEXT_LIMIT','Select at most 120,000 extracted characters per review. Split larger matters; sources are never silently truncated.')
            if body.options.compare_with_governing_law and not body.options.jurisdiction:
                raise APIError(422,'JURISDICTION_REQUIRED','Specify jurisdiction for governing-law comparison.')
            if sum(j['status'] not in TERMINAL for j in store.all(tenant, 'job')) >= 20:
                raise APIError(429, 'QUEUE_FULL', 'Wait for queued jobs to finish.', True)
            rid, jid = str(uuid4()), str(uuid4())
            report = {'id':rid,'job_id':jid,'status':'queued','focus_question':body.focus_question,'options':body.options.model_dump(mode='json'), 'source_document_ids':ids,'created_at':datetime.now(timezone.utc).isoformat(),'model':model_metadata(),'version':max(r['version'] for r in store.all(tenant,'review') if r['root_review_id']==previous['root_review_id'])+1 if previous else 1,'root_review_id':previous['root_review_id'] if previous else rid,'previous_review_id':previous['id'] if previous else None,'key_facts':[],'contradictions':[],'missing_information':[],'relevant_evidence':[],'claims':[],'citations':[],'warnings':[],'risk_summary':{'overall':'undetermined','rationale':'Review pending.','items':[]},'confidence':confidence(0,'Review pending.'),'failure':None}
            job = {'id':jid,'workflow':'review','resource_id':rid,'status':'queued','progress':0,'created_at':report['created_at'],'result_id':None,'warnings':[],'failure':None}
            store.save(tenant, 'review', report)
            store.save(tenant, 'job', job)
            store.db.execute('INSERT INTO queue VALUES(?,?,?,?)', (jid,tenant,rid,'queued'))
            store.event(jid, 'job.progress', status='queued', progress=0, message='Review queued')
            worker.wake.set()
        return envelope(request, {'review_id':rid,'job_id':jid,'status':'queued','events_url':f'/api/v1/jobs/{jid}/events'})

    @app.post('/api/v1/reviews', status_code=202)
    def new(request: Request, body: CreateReview):
        return idempotent(request, body.model_dump(mode='json'), lambda: create(request, body))

    @app.get('/api/v1/reviews')
    def listing(request: Request):
        return envelope(request, {'items': sorted(store.all(request.state.tenant,'review'),key=lambda r:r['created_at'],reverse=True)[:100]})

    @app.get('/api/v1/reviews/{rid}')
    def read(rid: UUID, request: Request): return envelope(request,get(request.state.tenant,'review',rid))

    @app.post('/api/v1/reviews/{rid}/rerun', status_code=202)
    def rerun(rid: UUID, request: Request, body: RerunReview):
        old = get(request.state.tenant,'review',rid)
        if old['status'] not in TERMINAL: raise APIError(409,'REVIEW_RUNNING','Wait for the current review.')
        return idempotent(request,body.model_dump(mode='json'),lambda: create(request,CreateReview(document_ids=old['source_document_ids'],focus_question=body.focus_question if body.focus_question is not None else old['focus_question'],options=body.options or old['options']),old))

    @app.get('/api/v1/reviews/{rid}/export')
    def export(rid: UUID, request: Request, format: Literal['json','docx','pdf']='json'):
        report = get(request.state.tenant,'review',rid)
        if report['status'] not in {'completed','completed_with_warnings'}:
            raise APIError(409,'REVIEW_NOT_READY','Only completed reports can be exported.')
        lines = ['LexiMind review',f'Version {report["version"]} | Model {report["model"]["version"]}',report['risk_summary']['rationale']]
        if report.get('overview'): lines.extend(['Overview',report['overview']['text']])
        for section in ['key_facts','timeline','contradictions','missing_information','relevant_evidence','warnings','citations']:
            lines.append(section.replace('_',' ').title())
            for item in report.get(section,[]):
                if section == 'citations':
                    lines.append(f'[{item["label"]}] {item["document_name"]}, page {item.get("page") or "body"}, offsets {item["start_offset"]}:{item["end_offset"]}: {item["quoted_text"]}')
                else: lines.append(json.dumps(item,ensure_ascii=False))
        stream = BytesIO()
        if format == 'json': content, media = json.dumps(report,indent=2), 'application/json'
        elif format == 'docx':
            from docx import Document
            document = Document()
            for line in lines: document.add_paragraph(line)
            document.save(stream)
            content, media = stream.getvalue(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        else:
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            from xml.sax.saxutils import escape
            style = getSampleStyleSheet()['BodyText']
            SimpleDocTemplate(stream).build([element for line in lines for element in (Paragraph(escape(line),style),Spacer(1,8))])
            content, media = stream.getvalue(), 'application/pdf'
        return Response(content,media_type=media,headers={'Content-Disposition':f'attachment; filename="review-{rid}.{format}"'})

    @app.get('/api/v1/reviews/{rid}/versions')
    def versions(rid: UUID, request: Request):
        report = get(request.state.tenant,'review',rid)
        return envelope(request,{'items':sorted([r for r in store.all(request.state.tenant,'review') if r['root_review_id']==report['root_review_id']],key=lambda r:(r['version'],r['created_at']))})

    @app.post('/api/v1/reviews/{rid}/feedback', status_code=201)
    def feedback(rid: UUID, request: Request, body: Feedback):
        from backend.models.registry import SPECS
        import hashlib
        report = get(request.state.tenant,'review',rid)
        if report['status'] not in {'completed','completed_with_warnings'}:
            raise APIError(409,'REVIEW_NOT_READY','Review must be complete before feedback.')
        records=[]
        for item in body.annotations:
            chunk=get(request.state.tenant,'chunk',item.chunk_id)
            a,b=item.start_offset-chunk['start_offset'],item.end_offset-chunk['start_offset']
            if chunk['document_id'] not in report['source_document_ids'] or not 0<=a<b<=len(chunk['text']) or item.label not in SPECS['review']:
                raise APIError(422,'INVALID_ANNOTATION','Use a review source span and supported label.')
            doc=get(request.state.tenant,'document',chunk['document_id'])
            records.append({'workflow':'review','text':chunk['text'][a:b],'label':item.label,'group_id':doc['sha256'],'human_approved':body.accepted,'use_for_training':body.use_for_training,'source_document_ids':report['source_document_ids'],'review_id':str(rid),'model_version':report['model']['version']})
        entry={'id':str(uuid4()),'review_id':str(rid),'source_document_ids':report['source_document_ids'],'records':records,'accepted':body.accepted,'use_for_training':body.use_for_training,'created_at':datetime.now(timezone.utc).isoformat()}
        store.save(request.state.tenant,'feedback',entry)
        return envelope(request,{'feedback_id':entry['id'],'training_eligible':body.accepted and body.use_for_training})

    @app.get('/api/v1/models/{workflow}/dataset')
    def dataset(workflow: str, request: Request, format: Literal['classification','sft']='classification'):
        from backend.models.registry import SPECS
        if workflow not in SPECS: raise APIError(404,'NOT_FOUND','Model unavailable.')
        latest={}
        for f in sorted(store.all(request.state.tenant,'feedback'),key=lambda f:(f.get('created_at',''),f['id'])):latest[f['review_id']]=f
        eligible=[f for f in latest.values() if f['accepted'] and f['use_for_training']]
        records=[r for f in eligible for r in f['records'] if r['workflow']==workflow]
        if format=='sft':
            from backend.review_training import sft_record
            records=[]
            if workflow=='review':
                for feedback in eligible:
                    report=get(request.state.tenant,'review',feedback['review_id'])
                    if report['model']['kind'] in {'local_llm','hosted_llm'} and report.get('overview'):
                        chunks=[c for c in store.all(request.state.tenant,'chunk') if c['document_id'] in report['source_document_ids']]
                        records.append(sft_record(report,chunks))
        if workflow=='drafting' and format=='sft':
            from backend.drafting_training import dataset as drafting_dataset
            records=drafting_dataset(store,request.state.tenant)
        if workflow=='research' and format=='sft':
            from backend.research import training_dataset
            records=training_dataset(store,request.state.tenant)
        if workflow=='chat' and format=='sft':
            from backend.chat import training_dataset
            records=training_dataset(store,request.state.tenant)
        return Response('\n'.join(json.dumps(r,ensure_ascii=False) for r in records),media_type='application/x-ndjson',headers={'Content-Disposition':f'attachment; filename="{workflow}-{format}-dataset.jsonl"'})

    @app.get('/api/v1/models')
    def registry(request: Request):
        return envelope(request,[{**model_metadata(),'topic_classifier':models.get('review').metadata} if m['workflow']=='review' else {**app.state.drafting_llm.metadata,'id':'leximind-drafting','workflow':'drafting','output_schema':'legal-draft-v1','prompt_version':'grounded-drafting-v1'} if m['workflow']=='drafting' else {**app.state.research_llm.metadata,'id':'leximind-research','workflow':'research','output_schema':'research-memo-v1','prompt_version':'grounded-research-v1'} if m['workflow']=='research' else {**app.state.chat_llm.metadata,'id':'leximind-chat','workflow':'chat','output_schema':'grounded-chat-v1','prompt_version':'grounded-chat-v1'} if m['workflow']=='chat' else {'id':'caselens-clause-auditor','workflow':'novelty','version':'source-integrity-audit-v1','kind':'deterministic_audit','available':True,'trainable':False,'output_schema':'source-integrity-audit-v1'} for m in models.describe()])

    @app.get('/api/v1/review/config')
    def configuration(request: Request):
        status=llm.status() if engine=='llm' else {'ready':True,'message':'Legacy extraction mode; LLM reasoning is disabled.','model':model_metadata()}
        return envelope(request,{'engine':engine,**status,'max_source_characters':MAX_SOURCE_CHARACTERS,'privacy':'Document content is sent to the deployment administrator’s configured model service.'})

    @app.post('/api/v1/notifications/{rid}/read')
    def mark_notification(rid: UUID, request: Request):
        job=get(request.state.tenant,'job',rid)
        if job['status'] not in {'failed','completed_with_warnings'}:
            raise APIError(404,'NOT_FOUND','Notification unavailable.')
        store.save(request.state.tenant,'notification_read',{'id':'read-'+str(rid),'read':True})
        return envelope(request,{'id':str(rid),'read':True})
