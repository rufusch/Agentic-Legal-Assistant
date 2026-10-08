"""Transparent drafting intake templates; not certified court filing rules."""
import re
from uuid import uuid4

TEMPLATES = {
    'bail_application': [('applicant_name','Applicant’s full name'), ('case_number','FIR / crime / case number'), ('allegations','Alleged offences and relevant events'), ('arrest_status','Arrest status and relevant dates'), ('relief','Bail relief requested'), ('grounds','Proposed grounds and supporting circumstances')],
    'petition': [('petitioner','Petitioner’s name and capacity'), ('respondent','Respondent’s name and capacity'), ('events','Material events and dates'), ('relief','Orders requested'), ('grounds','Grounds relied upon')],
    'notice': [('sender','Sender’s name and address'), ('recipient','Recipient’s name and service address'), ('events','Events giving rise to the notice'), ('demand','Action or payment demanded'), ('response_deadline','Requested response deadline')],
    'affidavit': [('deponent','Deponent’s name and capacity'), ('statements','Statements to be affirmed'), ('knowledge_basis','Personal knowledge or source of each statement'), ('execution_place','Place of affirmation'), ('execution_date','Date of affirmation')],
    'contract_clause': [('parties','Parties and their roles'), ('clause_purpose','Purpose of the clause'), ('obligations','Agreed obligations and exceptions'), ('effective_date','Effective date or triggering conditions')],
}


def requirements(body):
    document_type = body['document_type'].strip().lower().replace(' ', '_').replace('-', '_')
    if document_type in {'anticipatory_bail_application','regular_bail_application'}:
        document_type = 'bail_application'
    fields = [('jurisdiction','Applicable jurisdiction'), ('instructions','What should the draft achieve?')]
    if document_type in {'bail_application','petition','affidavit'}: fields.append(('court','Court or forum, if applicable'))
    fields += TEMPLATES.get(document_type, [('parties','Parties and their roles'),('events','Material facts and dates'),('relief','Requested outcome')])
    result = []
    for key, question in fields:
        value = body.get(key) if key in {'jurisdiction','instructions','court'} else body['facts'].get(key)
        result.append({'id':str(uuid4()),'key':key,'question':question,'rationale':'Needed to produce a specific draft without inventing information. This intake template is not a certified jurisdictional filing checklist.','required':key in {'jurisdiction','instructions'},'answer_type':'long_text' if key in {'instructions','events','grounds','statements','allegations','obligations'} else 'short_text','current_answer':value,'source':'template'})
    return result


def missing(items):
    return [r for r in items if r.get('current_answer') is None or not str(r['current_answer']).strip()]


def refresh_status(draft):
    draft['status'] = 'awaiting_information' if missing(draft['requirements']) else 'ready_to_draft'
    return draft


MONTH = r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.?'
DATE = rf'(?:\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH},?\s+\d{{4}}|{MONTH}\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}})'
def label(*names): return r'(?im)^[ \t]*(?:' + '|'.join(names) + r')[ \t]*[:\-][ \t]*([A-Z][^\n:;(]{1,118}?)[ \t]*(?:[,;.(]|$)'
PATTERNS = {
    'applicant_name': [label('Applicant', 'Accused', 'Applicant/Accused', 'Petitioner/Accused')],
    'petitioner': [label('Petitioner', 'Appellant', 'Plaintiff', 'Complainant')],
    'respondent': [label('Respondent', 'Defendant', 'Opposite Party')],
    'deponent': [label('Deponent'), r'\bI,\s+([A-Z][A-Za-z .]{2,80}?),\s+(?:son|daughter|wife|aged)\b'],
    'sender': [label('From', 'Sender')],
    'recipient': [label('To', 'Recipient', 'Addressee', 'Noticee')],
    'parties': [r'(?i)\bbetween\s+([A-Z][^\n,(]{2,120}?)\s*(?:\([^)\n]{0,120}\)\s*)?,?\s+and\s+([A-Z][^\n,(.]{2,120})'],
    'case_number': [r'(?i)\b((?:FIR|F\.I\.R\.|Crime|C\.R\.|Case|Bail Application|B\.A\.|Writ Petition|W\.P\.|Criminal Appeal|Crl\.A\.)\s*(?:No\.?|Number)\s*[:.\-]?\s*\d[A-Z0-9/\-.]*(?:\s*(?:of|/)\s*\d{4})?)'],
    'court': [r'(?im)^[ \t]*(?:BEFORE|IN)\s+THE\s+([^\n]*?COURT[^\n]*?)[ \t]*$'],
    'arrest_status': [rf'(?i)\b(arrested\s+on\s+{DATE})'],
    'response_deadline': [r'(?i)\b(within\s+(?:\d+|seven|ten|fourteen|fifteen|thirty|sixty|ninety)\s+(?:\(\d+\)\s+)?days)\b'],
    'effective_date': [rf'(?i)\beffective\s+(?:from|as\s+of)\s*[:\-]?\s*({DATE})'],
    'execution_date': [rf'(?im)^[ \t]*(?:Date|Dated)[ \t]*[:\-][ \t]*({DATE})'],
    'execution_place': [r'(?im)^[ \t]*Place[ \t]*[:\-][ \t]*([A-Z][A-Za-z .]{1,60}?)[ \t]*$'],
    'demand': [r'(?i)\b(?:sum|amount)\s+of\s+((?:Rs\.?|INR|₹)\s*[\d,]+(?:\.\d+)?(?:\s*/-)?)'],
}


def find(key, chunks, documents):
    """First deterministic match for a field in attached case documents, with its exact quoted span; None if absent."""
    docs = {d['id']: d for d in documents}
    for chunk in sorted(chunks, key=lambda c: (c['document_id'], c.get('source_part', 1), c['start_offset'])):
        doc = docs.get(chunk['document_id'])
        if not doc or doc['metadata'].get('document_type') in {'statute', 'judgment', 'secondary', 'past_draft', 'user_input'}: continue
        text = chunk['text']
        for pattern in PATTERNS.get(key, []):
            for m in re.finditer(pattern, text):
                parts = [g.strip(' \t,;') for g in m.groups() if g and g.strip(' \t,;')]
                raw = m.group(0); start = m.start() + len(raw) - len(raw.lstrip()); end = m.end() - (len(raw) - len(raw.rstrip()))
                quote = text[start:end]
                # Never answer without an exact quoted span that contains every extracted value.
                if not parts or not quote or not all(p in quote for p in parts): continue
                return {'value': ' and '.join(parts), 'citation': {'document_id': doc['id'], 'document_name': doc['name'], 'chunk_id': chunk['id'], 'quote': quote,
                    'start_offset': chunk['start_offset'] + start, 'end_offset': chunk['start_offset'] + end}}
    return None


def prefill(draft, documents, chunks):
    """Fill empty template fields from attached documents with exact source quotes; the user can override any value."""
    for item in draft['requirements']:
        if item['key'] in {'jurisdiction', 'instructions'} or (item.get('current_answer') is not None and str(item['current_answer']).strip()): continue
        hit = find(item['key'], chunks, documents)
        item['found_in_source'] = bool(hit)
        if not hit: continue
        item.update(current_answer=hit['value'], source='document', citation=hit['citation'], rationale='Found in an attached document (exact quote shown). Confirm or override it before drafting.')
        if item['key'] == 'court': draft['court'] = hit['value']
        else: draft['facts'][item['key']] = hit['value']
    return draft
