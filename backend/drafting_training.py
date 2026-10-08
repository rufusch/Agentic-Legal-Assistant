"""Approved, version-specific drafting SFT export; never trains from unchecked proposals."""
import hashlib
import json
from backend.llm_review_engine import source_catalog


def target_from_draft(draft, chunks):
    from backend.drafting_schema import ProposedDraft
    catalog=source_catalog(chunks)
    lookup={(ref['chunk']['id'],ref['quote']):key for key,ref in catalog.items()}
    refs={c['id']:lookup[(c['chunk_id'],c['quoted_text'])] for c in draft['citations']}
    target = {'sections':[{'heading':s['heading'],'blocks':[{'kind':b['kind'],'text':b['text'],'statement_type':b['statement_type'],'source_ids':[refs[c] for c in b['citation_ids']]} for b in s['blocks']]} for s in draft['sections']]}
    return ProposedDraft.model_validate(target).model_dump()


def dataset(store,tenant):
    latest={}
    for f in sorted(store.all(tenant,'draft_feedback'),key=lambda f:(f['created_at'],f['id'])):latest[(f['draft_id'],f['version'])]=f
    records=[]
    for item in store.all(tenant,'draft_training'):
        feedback=latest.get((item['draft_id'],item['version']))
        draft=store.get(tenant,'draft',item['draft_id'])
        if not feedback or not feedback['accepted'] or not feedback['use_for_training'] or not draft or draft['version']!=item['version'] or draft['needs_verification'] or draft['status'] not in {'completed','completed_with_warnings'}:continue
        docs=[store.get(tenant,'document',rid) for rid in item['source_document_ids']]
        if any(d is None for d in docs):continue
        hashes=sorted(d['sha256'] for d in docs)
        records.append({'workflow':'drafting','consented':True,'human_approved':True,'draft_id':item['draft_id'],'version':item['version'],'model_id':draft['model']['id'],'model_version':draft['model']['version'],'schema_version':'legal-draft-v1','source_group':hashlib.sha256('|'.join(hashes).encode()).hexdigest(),'source_hashes':hashes,'prompt_version':'grounded-drafting-v1','messages':[*item['messages'],{'role':'assistant','content':json.dumps(item['target'],ensure_ascii=False)}]})
    return records
