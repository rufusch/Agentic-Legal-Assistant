"""Conservative source-extractive review. No invented authorities or legal conclusions."""
import re
from collections import defaultdict
from datetime import datetime
from uuid import uuid4

from backend.retrieval import terms

LABELS={'payment':'Payment terms','termination':'Termination and notice','parties':'Named parties','governing_law':'Governing-law wording','missing_material':'Missing material stated in source','other':'Source passage'}
MONTHS='January February March April May June July August September October November December'.split()
DATE_PATTERN=r'\b\d{1,2}\s+(?:'+'|'.join(MONTHS)+r')\s+\d{4}\b'


def uid(): return str(uuid4())


def confidence(score,explanation):
    return {'score':score,'level':'high' if score>=.85 else 'medium' if score>=.5 else 'low' if score else 'unavailable','explanation':explanation}


def warning(kind,title,message,severity='warning',citations=None):
    return {'id':uid(),'type':kind,'severity':severity,'title':title,'message':message,'citation_ids':citations or [],'resolvable':False}


def sentences(chunk):
    for line in re.finditer(r'[^\n]+',chunk['text']):
        for span in re.finditer(r'.+?(?:[.!?](?=\s+[A-Z])|$)',line.group()):
            raw=span.group()
            text=raw.strip()
            if len(text)<12: continue
            if text.isupper() and len(text.split()) < 8: continue
            start=line.start()+span.start()+len(raw)-len(raw.lstrip())
            yield text,start,start+len(text)


def generate(report,documents,chunks,model,check_cancelled=lambda:False):
    by_id={d['id']:d for d in documents}
    report={**report,'claims':[],'citations':[],'key_facts':[],'contradictions':[],'missing_information':[],'relevant_evidence':[],'authority_coverage':[],'warnings':[]}
    citations, statements=[],[]
    focus=set(terms(report['focus_question']))
    for chunk in chunks:
        if check_cancelled(): return None
        for text,start,end in sentences(chunk):
            label,score=model.classify(text)
            # Trained topic output categorizes sources; it cannot override factual verification.
            statements.append({'text':text,'chunk':chunk,'start':start,'end':end,'label':label,'score':score,'priority':len(focus & set(terms(text)))})
    statements.sort(key=lambda s:(-s['priority'],s['chunk']['document_id'],s['chunk'].get('source_part',1),s['start']))
    selected=[s for s in statements if s['label'] != 'other'][:80]
    if len([s for s in statements if s['label']!='other']) > 80:
        report['warnings'].append(warning('partial_processing','Review output limit','Only the first 80 prioritized findings are included. Narrow the document scope or focus question.'))
    by_topic=defaultdict(list)
    for statement in selected:
        chunk,text,label=statement['chunk'],statement['text'],statement['label']
        doc=by_id[chunk['document_id']]
        cid,claim_id=uid(),uid()
        citation={'id':cid,'label':f'S{len(citations)+1}','document_id':doc['id'],'document_name':doc['name'],'chunk_id':chunk['id'],'page':chunk.get('page'),'section':chunk.get('section'),'start_offset':chunk['start_offset']+statement['start'],'end_offset':chunk['start_offset']+statement['end'],'quoted_text':text,'jurisdiction':doc['metadata'].get('jurisdiction')}
        citations.append(citation)
        report['claims'].append({'id':claim_id,'text':text,'citation_ids':[cid],'verification_status':'supported','confidence':.99,'warning':'Supported as an exact source quotation; source truth and legal effect are not independently verified.'})
        category='law' if doc['metadata'].get('document_type')=='statute' else 'precedent' if doc['metadata'].get('document_type')=='judgment' else 'clause'
        report['relevant_evidence'].append({'id':uid(),'title':LABELS.get(label,'Source passage'),'summary':text,'category':category,'citation_ids':[cid]})
        if len(report['key_facts'])<30:
            report['key_facts'].append({'id':uid(),'label':LABELS.get(label,'Source passage'),'value':text,'claim_id':claim_id,'citation_ids':[cid]})
        # Always check deterministic signals, even when a trained classifier predicts another topic.
        signals=[]
        if re.search(r'\bpay(?:ment|able)?\b|invoice',text,re.I):
            signals.extend(('Payment date',d.casefold()) for d in re.findall(DATE_PATTERN,text,re.I))
            signals.extend(('Payment amount',a.replace(',','').replace(' ','').upper()) for a in re.findall(r'\b(?:INR|USD|EUR|GBP)\s*[\d,]+(?:\.\d+)?',text,re.I))
        if re.search(r'terminat|notice',text,re.I):
            signals.extend(('Termination notice',d) for d in re.findall(r'\b(\d+)\s*days?\b',text,re.I))
        for topic,value in signals:
            by_topic[topic].append({'value':value,'statement':text,'citation_ids':[cid],'document_id':doc['id']})
        if re.search(r'not attached|not included|missing|no signatures|unsigned|not supplied',text,re.I):
            report['missing_information'].append({'id':uid(),'item':text,'why_it_matters':'The source explicitly identifies absent material. Its contents or effect cannot be assumed.','suggested_action':'Obtain the referenced material or confirm its absence before relying on this review.','severity':'high','citation_ids':[cid]})
    for topic,sides in by_topic.items():
        if len({s['document_id'] for s in sides})<2 or len({s['value'] for s in sides})<2: continue
        unique=[]
        for side in sides:
            if not any(s['statement']==side['statement'] for s in unique): unique.append(side)
        report['contradictions'].append({'id':uid(),'topic':topic,'description':f'Selected sources contain different values for {topic.lower()}. Confirm whether they address the same obligation and whether one supersedes another.','severity':'high','sides':[{'statement':s['statement'],'citation_ids':s['citation_ids']} for s in unique],'legal_effect':None,'resolution':'Check document scope, execution and amendment history; no legal priority is inferred.','confidence':confidence(.65,'Different source values were found. Their applicability and legal priority remain unresolved.')})
    for doc in documents:
        report['warnings'].extend(doc.get('warnings',[]))
    if report['missing_information']:
        report['warnings'].append(warning('missing_information','Missing source material','Referenced material is explicitly absent. Review the missing-information section.','critical',[c for m in report['missing_information'] for c in m['citation_ids']]))
    if report['contradictions']:
        report['warnings'].append(warning('contradiction','Potential source conflicts','Different values are preserved on both sides. Applicability has not been resolved.','critical',[c for x in report['contradictions'] for s in x['sides'] for c in s['citation_ids']]))
    options=report['options']
    if options['compare_with_governing_law']:
        for doc in documents:
            metadata=doc['metadata']
            if metadata.get('document_type') not in {'statute','judgment'}: continue
            effective=metadata.get('effective_from') or metadata.get('document_date')
            eligibility='metadata_unverified'
            try:
                date_value=datetime.fromisoformat(effective).date() if effective else None
                as_of=datetime.fromisoformat(options['as_of_date']).date() if options['as_of_date'] else None
                eligibility='date_missing' if date_value is None or as_of is None else 'future_at_as_of' if date_value>as_of else 'date_within_scope'
            except (TypeError,ValueError): eligibility='invalid_date_metadata'
            if metadata.get('jurisdiction') != options['jurisdiction']: eligibility='jurisdiction_mismatch'
            report['authority_coverage'].append({'document_id':doc['id'],'authority_type':metadata['document_type'],'jurisdiction':metadata.get('jurisdiction'),'effective_at':effective,'as_of_date':options['as_of_date'],'treatment':'unknown','eligibility':eligibility,'comparison_status':'source_identified_only'})
        report['warnings'].append(warning('weak_authority','Governing-law comparison is limited','Uploaded authority excerpts are identified by type, jurisdiction and as-of date. Currency, treatment and legal application have not been independently verified; no law-compliance conclusion is made.'))
        if not report['authority_coverage']:
            report['warnings'].append(warning('weak_authority','No dated authority supplied','Add a statute or judgment with jurisdiction and effective/date metadata to supply authority evidence.'))
    report['warnings'].append(warning('partial_processing','Extractive baseline coverage','This review identifies supported source passages and deterministic differences. It may miss legal issues, implied conflicts or omitted facts; it does not determine enforceability.','info'))
    if not citations:
        report['warnings'].append(warning('missing_information','Insufficient evidence','No relevant source passages were identified. Broaden the source scope; no factual or legal conclusion can be made.'))
    report['citations']=citations
    risks=[{'risk':f'Unresolved differences in {x["topic"].lower()}.','severity':'high','likelihood':'unknown','citation_ids':[c for side in x['sides'] for c in side['citation_ids']]} for x in report['contradictions']]
    report['risk_summary']={'overall':'high' if risks else 'undetermined','rationale':'Source differences require reconciliation; severity indicates review priority, not a prediction of legal outcome.' if risks else 'Available evidence does not establish an overall legal risk level. Absence of detected issues is not a clean legal opinion.','items':risks}
    report['confidence']=confidence(.6 if citations else .2,'Confidence reflects source extraction only. Legal effect, authority currency and complete issue coverage remain unverified.')
    report['status']='completed_with_warnings'
    return report
