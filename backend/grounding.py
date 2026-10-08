"""Deterministic material-value guard and inspectable source-integrity audits.

Numeric agreement and exact spans are necessary checks, not proof of entailment.
"""
import re
from decimal import Decimal


def numbers(text):
    text=re.sub(r'\b(INR|USD|Rs)(?=\d)',r'\1 ',str(text),flags=re.I)
    values=set()
    for token in re.findall(r'(?<!\w)\d[\d,]*(?:\.\d+)?', str(text)):
        try: values.add(str(Decimal(token.replace(',','')).normalize()))
        except Exception: pass
    return values


def material_values_supported(text, quotes):
    return numbers(text) <= numbers('\n'.join(quotes))


def audit_claims(result):
    rows=list(result.get('claims',[]))
    # Proposed contractual language can carry material terms even when it is not
    # classified as an assertion of historical fact. Audit its evidence too.
    known={r['text'] for r in rows}
    for section in result.get('sections',[]):
        for block in section.get('blocks',[]):
            if block.get('statement_type')!='placeholder' and block['text'] not in known and (block.get('citation_ids') or numbers(block['text'])):
                rows.append({'id':block['id'],'text':block['text'],'citation_ids':block.get('citation_ids',[]),'verification_status':block.get('verification_status','unknown')})
                known.add(block['text'])
    if 'key_facts' in result:
        def add(item,text,refs):
            if text: rows.append({'id':item.get('id','overview'),'text':text,'citation_ids':refs,'verification_status':'model_checked_interpretation' if result.get('verification',{}).get('method')=='exact_source_spans_and_second_llm_pass' else 'source_linked_interpretation'})
        overview=result.get('overview') or {}
        add(overview,overview.get('text'),overview.get('citation_ids',[]))
        for item in result.get('timeline',[]): add(item,' '.join(filter(None,[item.get('date'),item.get('event')])),item.get('citation_ids',[]))
        for item in result.get('relevant_evidence',[]): add(item,item.get('summary'),item.get('citation_ids',[]))
        for item in result.get('missing_information',[]): add(item,' '.join(item.get(k,'') for k in ['item','why_it_matters','suggested_action']),item.get('citation_ids',[]))
        for item in result.get('risk_summary',{}).get('items',[]): add(item,item.get('risk'),item.get('citation_ids',[]))
        for item in result.get('contradictions',[]):
            refs=list(dict.fromkeys(c for side in item['sides'] for c in side['citation_ids']))
            add(item,item.get('description'),refs)
            for side in item['sides']: add({'id':str(item['id'])+'-'+str(len(rows))},side['statement'],side['citation_ids'])
    return rows


def inspect(result, load_chunk):
    citations={str(c['id']):c for c in result.get('citations',[])}
    checks={};rows=[]
    for cid,c in citations.items():
        try:
            chunk=load_chunk(str(c['document_id']),str(c['chunk_id']))
            quote=c['quoted_text'];start=c.get('start_offset');end=c.get('end_offset')
            valid=bool(quote) and str(chunk['document_id'])==str(c['document_id']) and quote in chunk['text']
            if start is not None or end is not None:
                valid=valid and start is not None and end is not None and start>=chunk['start_offset'] and end>start and chunk['text'][start-chunk['start_offset']:end-chunk['start_offset']]==quote
            checks[cid]={'valid':bool(valid),'reason':'Exact stored source span' if valid else 'Quote or offsets do not resolve'}
        except Exception: checks[cid]={'valid':False,'reason':'Source unavailable in this workspace'}
    for claim in audit_claims(result):
        refs=list(map(str,claim.get('citation_ids',[])))
        span_valid=bool(refs) and all(checks.get(r,{}).get('valid') for r in refs)
        values_valid=material_values_supported(claim['text'],[citations[r]['quoted_text'] for r in refs if r in citations])
        rows.append({'id':str(claim['id']),'text':claim['text'],'citation_ids':refs,'source_integrity':span_valid,'material_values_present':values_valid,'support_status':claim.get('verification_status','unknown'),'requires_human_review':True})
    traced=sum(r['source_integrity'] for r in rows)
    pending=bool(result.get('needs_verification'))
    return {'version':'source-integrity-audit-v1','resource_id':result['id'],'status':result['status'],
        'claim_count':len(rows),'citation_count':len(citations),'traceable_claims':traced,
        'traceability_score':traced/len(rows) if rows else None,
        'source_integrity_passed':bool(rows) and not pending and all(r['source_integrity'] and r['material_values_present'] for r in rows) and all(c['valid'] for c in checks.values()),
        'pending_edit_verification':pending,'abstained':not rows,'claims':rows,
        'citations':[{**c,'audit':checks[cid]} for cid,c in citations.items()],
        'warnings':result.get('warnings',[]),
        'limitations':['Source traceability does not establish truth, entailment, legal correctness or current authority.',
            'An empty answer has no groundedness score; abstention is not scored as a perfect answer.',
            'Model support checks use the configured model; independent human assessment remains necessary.']}


def install(app,store,get,envelope,APIError):
    import json
    from typing import Literal
    from uuid import UUID
    from fastapi import Request
    from fastapi.responses import Response
    kinds={'review':'review','drafting':'draft','research':'research','chat':'chat_message'}
    def audit(request,workflow,rid):
        tenant=request.state.tenant;result=get(tenant,kinds[workflow],rid)
        if result['status'] not in {'completed','completed_with_warnings'}:
            raise APIError(409,'OUTPUT_NOT_READY','Complete and verify the workflow output before auditing it.')
        def chunk(document,cid):
            get(tenant,'document',document);item=get(tenant,'chunk',cid)
            if item['document_id']!=document: raise ValueError('Document mismatch')
            return item
        return {**inspect(result,chunk),'workflow':workflow}

    @app.get('/api/v1/grounding-audit/outputs')
    def outputs(request:Request):
        rows=[]
        for workflow,kind in kinds.items():
            for r in store.all(request.state.tenant,kind):
                if r['status'] in {'completed','completed_with_warnings'} and (workflow!='chat' or r['role']=='assistant'):
                    rows.append({'id':r['id'],'workflow':workflow,'title':r.get('title') or r.get('question') or r.get('focus_question') or 'Contract / Case Review','created_at':r['created_at'],'claim_count':len(audit_claims(r))})
        return envelope(request,{'items':sorted(rows,key=lambda r:r['created_at'],reverse=True)[:100]})

    @app.get('/api/v1/grounding-audit')
    def report(request:Request,workflow:Literal['review','drafting','research','chat'],resource_id:UUID):
        return envelope(request,audit(request,workflow,resource_id))

    @app.get('/api/v1/grounding-audit/export')
    def export(request:Request,workflow:Literal['review','drafting','research','chat'],resource_id:UUID):
        return Response(json.dumps(audit(request,workflow,resource_id),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="grounding-audit-{resource_id}.json"'})
