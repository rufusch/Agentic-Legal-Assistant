"""Literal, attributed intake assembly for a bail application with structured facts.

This is document assembly, not a model's finding that allegations or law are true.
Every supplied value must resolve to its exact captured intake field before use.
"""
import json
import re
from uuid import uuid4
from backend.official_sources import citation_provenance
from backend.review_engine import warning, confidence


def prefill_notice_instructions(draft):
    """Copy explicit party, payment and deadline spans; never infer missing values."""
    if 'notice' not in draft['document_type'].casefold():return
    text=draft['instructions'];facts=draft['facts']
    parties=re.search(r'\bfrom\s+(.+?)\s+to\s+(.+?)(?=,|\s+(?:requesting|demanding|regarding|for)\b)',text,re.I)
    if parties:
        for key,value in zip(('sender','recipient'),parties.groups()):
            if not facts.get(key):facts[key]=value.strip()
    amount=re.search(r'\b(?:payment of|pay)\s+(?:INR|USD|Rs\.?)\s*[\d,]+(?:\.\d+)?',text,re.I)
    deadline=re.search(r'\b(?:by|before)\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})',text,re.I)
    if amount and not facts.get('demand'):facts['demand']=amount.group()
    if deadline and not facts.get('response_deadline'):facts['response_deadline']=deadline.group(1)


def has_structured_bail(draft):
    if 'bail' not in draft['document_type'].casefold():return None
    facts=draft.get('facts',{})
    required=('applicant_name','case_number','allegations','arrest_status','grounds','relief')
    return all(isinstance(facts.get(k),str) and facts[k].strip() for k in required)


def has_structured_notice(draft):
    facts=draft.get('facts',{})
    return 'notice' in draft['document_type'].casefold() and all(isinstance(facts.get(k),str) and facts[k].strip() for k in ('sender','recipient','demand','response_deadline'))


def has_structured_draft(draft):return has_structured_bail(draft) or has_structured_notice(draft)


def assemble_structured(draft, catalog, documents, model, verification_info):
    if not has_structured_draft(draft):return None
    facts=draft['facts']
    notice=has_structured_notice(draft)
    required=('sender','recipient','demand','response_deadline') if notice else ('applicant_name','case_number','allegations','arrest_status','grounds','relief')
    docs={d['id']:d for d in documents};fields={}
    for key,ref in catalog.items():
        if ref['chunk']['document_id']!=draft.get('context_document_id'):continue
        line=ref['quote']
        if ': ' not in line:continue
        name,raw=line.split(': ',1)
        try:value=json.loads(raw)
        except ValueError:continue
        expected=facts.get(name[6:]) if name.startswith('facts.') else draft.get(name)
        if value==expected:fields[name]=(key,value)
    if not all('facts.'+k in fields for k in required) or 'document_type' not in fields:return None
    if draft.get('court') and 'court' not in fields:return None
    result={**draft,'sections':[],'claims':[],'citations':[],'authorities':[],
        'unresolved_placeholders':[],'warnings':[],'failure':None,'needs_verification':False,
        'status':'completed_with_warnings','model':model,
        'verification':{**verification_info,'method':'exact_captured_intake_fields','items':[]}}
    citations={}
    def uid():return str(uuid4())
    def add_section(heading):
        section={'id':uid(),'heading':heading,'order':len(result['sections']),'blocks':[]}
        result['sections'].append(section);return section
    def add(section,text,names=(),kind='fact'):
        bid=uid();cids=[]
        for name in names:
            key,_=fields[name];ref=catalog[key];chunk=ref['chunk'];doc=docs[chunk['document_id']]
            if key not in citations:
                citations[key]={'id':uid(),'label':f'S{len(citations)+1}','document_id':doc['id'],'document_name':doc['name'],'chunk_id':chunk['id'],'quoted_text':ref['quote'],'page':chunk.get('page'),'section':chunk.get('section'),'start_offset':chunk['start_offset']+ref['offset'],'end_offset':chunk['start_offset']+ref['offset']+len(ref['quote']),**citation_provenance(doc)}
            cids.append(citations[key]['id'])
        block={'id':bid,'kind':'placeholder' if kind=='placeholder' else 'paragraph','text':text,'claim_ids':[],'citation_ids':cids,'editable':True,'statement_type':kind,'verification_status':'placeholder' if kind=='placeholder' else 'checked'}
        if kind=='fact':
            cid=uid();block['claim_ids']=[cid]
            result['claims'].append({'id':cid,'text':text,'citation_ids':cids,'verification_status':'partially_supported','confidence':.55,'warning':'Exact user-provided intake, reproduced as instructions or allegations; not independently established truth.'})
        if kind=='placeholder':
            result['unresolved_placeholders'].append({'id':uid(),'token':text,'description':'Supply the missing detail or a verified source.','requirement_id':None})
        else:result['verification']['items'].append({'id':bid,'supported':True,'reason':'Literal assembly from matched captured intake fields; no legal inference.'})
        section['blocks'].append(block)
    if notice:
        section=add_section('Notice')
        add(section,'From: '+facts['sender'],['facts.sender'])
        add(section,'To: '+facts['recipient'],['facts.recipient'])
        invoice=re.search(r'\binvoice\s+([A-Z0-9][-A-Z0-9/]*)\s+dated\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})',draft['instructions'],re.I)
        if invoice and 'instructions' in fields:
            add(section,'Reference: invoice '+invoice.group(1)+' dated '+invoice.group(2),['instructions'])
        if isinstance(facts.get('events'),str) and facts['events'].strip() and 'facts.events' in fields:
            add(section,'The sender states: '+facts['events'],['facts.events'])
        add(section,facts['sender']+' requests the following from '+facts['recipient']+': '+facts['demand']+'.',['facts.sender','facts.recipient','facts.demand'],kind='draft_language')
        add(section,'Please respond or comply by '+facts['response_deadline']+'.',['facts.response_deadline'],kind='draft_language')
        add(section,'Please provide written confirmation of your response.',kind='draft_language')
        signature=add_section('Signature');add(signature,'For '+facts['sender'],['facts.sender'],kind='draft_language')
        add(signature,'[DATE]\n[NAME AND SIGNATURE OF AUTHORISED SIGNATORY]',kind='placeholder')
        result['citations']=list(citations.values());result['confidence']=confidence(.55,'Literal source traceability to user-provided intake; no assessment of legal merits or notice requirements.')
        result['warnings']=[warning('missing_information','Complete the signature details','The date and authorised signatory are marked in brackets.'),warning('partial_processing','Working notice from your instructions','No statute, penalty, interest or legal consequence has been invented.','info')]
        return result
    title=add_section('Cause title')
    if draft.get('court'):add(title,'Before: '+draft['court'],['court'])
    else:add(title,'[COURT NAME]',kind='placeholder')
    add(title,'Applicant: '+facts['applicant_name'],['facts.applicant_name'])
    add(title,'Case / Crime number: '+facts['case_number'],['facts.case_number'])
    add(title,'[RESPONDENT / PROSECUTING AUTHORITY]',kind='placeholder')
    add(title,draft['document_type'],['document_type'],kind='draft_language')
    background=add_section('Background')
    add(background,'The applicant states: '+facts['arrest_status'],['facts.arrest_status'])
    supplied=add_section('Facts')
    add(supplied,'The applicant provides the following account, including the allegations and response: '+facts['allegations'],['facts.allegations'])
    grounds=add_section('Grounds')
    parts=re.split(r'\n+|(?<=\.)\s+(?=\(?\d+[.)])',facts['grounds'])
    for part in parts:
        part=part.strip()
        if not part:continue
        if re.search(r'\b(?:held|ruled|constitution|constitutional|article\s*\d|supreme court|high court|entitled|binding precedent|violate|mandates?)\b',part,re.I):
            continue
        add(grounds,'The applicant submits: '+part,['facts.grounds'])
    if not grounds['blocks']:add(grounds,'[FACTUAL GROUNDS FOR BAIL]',kind='placeholder')
    authorities=add_section('Authorities')
    add(authorities,'[VERIFIED AUTHORITY NEEDED: applicable bail provision and any constitutional ground or precedent relied upon]',kind='placeholder')
    prayer=add_section('Prayer')
    add(prayer,'The applicant respectfully seeks: '+facts['relief'],['facts.relief'],kind='draft_language')
    # Conditions are offered only when explicitly supplied, never invented by a template.
    conditions=re.search(r'\bincluding\b[\s:,]*(.+)',facts['relief'],re.I|re.S)
    if conditions:
        section=add_section('Proposed bail conditions')
        add(section,'Proposed conditions, as instructed: '+conditions.group(1),['facts.relief'],kind='draft_language')
    signature=add_section('Signature')
    add(signature,'[PLACE AND DATE]\n[APPLICANT / ADVOCATE SIGNATURE]',kind='placeholder')
    result['citations']=list(citations.values())
    result['confidence']=confidence(.55,'Literal source traceability to user-provided intake; no assessment of legal merits or filing compliance.')
    result['warnings']=[warning('missing_information','Complete the marked details','Respondent, execution details and verified authority are marked in brackets.'),warning('partial_processing','Working draft from your supplied facts','Statements are attributed to the applicant. Legal propositions from intake were not certified or invented.','info')]
    return result
