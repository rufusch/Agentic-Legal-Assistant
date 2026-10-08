"""Transparent drafting intake templates; not certified court filing rules."""
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
