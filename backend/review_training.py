"""Consent-gated, source-grounded supervised examples for later review LLM fine-tuning."""
import hashlib
import json
from backend.llm_review_engine import SYSTEM, source_catalog
from backend.llm_review_schema import DraftAnalysis


def sft_record(report,chunks):
    citations={c['id']:c for c in report['citations']}
    catalog=source_catalog(chunks)
    lookup={(r['chunk']['id'],r['quote']):key for key,r in catalog.items()}
    def refs(ids):return [{'source_id':lookup[(citations[r]['chunk_id'],citations[r]['quoted_text'])]} for r in ids]
    def cited(text,ids):return {'text':text,'references':refs(ids)}
    target={'document_kind':report['document_kind'],'overview':cited(report['overview']['text'],report['overview']['citation_ids']),
        'key_facts':[{**cited(f['value'],f['citation_ids']),'label':f['label'],'assertion_type':f['assertion_type']} for f in report['key_facts'][:15]],
        'timeline':[{**cited(e['event'],e['citation_ids']),'date':e['date']} for e in report['timeline'][:12]],
        'contradictions':[{'topic':c['topic'],'explanation':c['description'],'severity':c['severity'],'sides':[cited(s['statement'],s['citation_ids']) for s in c['sides']]} for c in report['contradictions'][:8]],
        'missing_information':[{**cited(m['item'],m['citation_ids']),'why_it_matters':m['why_it_matters'],'suggested_action':m['suggested_action'],'severity':m['severity']} for m in report['missing_information'][:8]],
        'relevant_evidence':[{**cited(e['summary'],e['citation_ids']),'title':e['title'],'category':e['category']} for e in report['relevant_evidence'][:15]],
        'risks':[{**cited(r['risk'],r['citation_ids']),'severity':r['severity'],'likelihood':r['likelihood']} for r in report['risk_summary']['items'][:8]]}
    target=DraftAnalysis.model_validate(target).model_dump(mode='json')
    packet={'focus_question':report['focus_question'],'options':report['options'],'sources':[{'source_id':key,'document_id':r['chunk']['document_id'],'page':r['chunk'].get('page'),'text':r['quote']} for key,r in catalog.items()]}
    group=hashlib.sha256('|'.join(sorted(report['coverage']['source_hashes'].values())).encode()).hexdigest()
    return {'workflow':'review','format':'messages-sft-v1','group_id':group,'human_approved':True,'use_for_training':True,'review_id':report['id'],'model':report['model'],'source_document_ids':report['source_document_ids'],'target_limits':'Per-section output limits match DraftAnalysis; additional report findings are omitted from this training target.','messages':[{'role':'system','content':SYSTEM},{'role':'user','content':json.dumps(packet,ensure_ascii=False)},{'role':'assistant','content':json.dumps(target,ensure_ascii=False)}]}
