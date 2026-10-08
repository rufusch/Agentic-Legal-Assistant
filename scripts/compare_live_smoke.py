"""Single-pass RAG baseline on the identical input used by release_smoke's chat.

This is a development smoke comparison, not a claim to beat a frontier baseline.
"""
import argparse
import json
import time
from pathlib import Path
from backend.chat import Answer
from backend.models.review_llm import LocalReviewLLM
from scripts.evaluate_grounding import evaluate
from backend.retrieval import terms


def best_span(claim,text):
    """(start, end) of the source sentence sharing the most terms with the claim."""
    import re
    spans=[m.span() for m in re.finditer(r'[^.!?\n]+[.!?]?',text) if m.group().strip()] or [(0,len(text))]
    want=set(terms(claim))
    start,end=max(spans,key=lambda s:(len(want&set(terms(text[s[0]:s[1]]))),-s[0]))
    while text[start].isspace():start+=1
    return start,end


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('smoke',type=Path);p.add_argument('--output-dir',type=Path,required=True);args=p.parse_args()
    data=json.loads(args.smoke.read_text(encoding='utf-8'));chat=data['workflows']['chat']['result']
    if chat.get('status') not in {'completed','completed_with_warnings'}:raise ValueError('Real-model chat failed; retain its failure record instead of inventing a prediction')
    text='SYNTHETIC TEST CONTRACT. Example Buyer must pay Example Supplier INR 5000 within ten days of invoice.'
    question=chat['question'];source={'id':'E1','text':text};dataset=[{'id':'release-chat','split':'development_smoke','question':question,'sources':[source],'gold_source_ids':['E1'],'answerable':True}]
    model=LocalReviewLLM.from_env();started=time.monotonic()
    messages=[{'role':'system','content':'Answer the question concisely using the supplied retrieved source only. Return a single proposition with source_ids. Do not invent facts or citations.'}, {'role':'user','content':json.dumps({'question':question,'sources':[{'source_id':'E1','text':text}]})}]
    raw=Answer.model_validate(model.complete(messages,Answer.model_json_schema()))
    # A whole-source quote is trivially a substring (traceability always 1.0). Cite only the single source
    # sentence that best matches the claim, so the numeric guard and span checks test something real.
    def citation(claim,ref):
        if ref!='E1':return {'source_id':ref,'quote':''}
        start,end=best_span(claim,text);return {'source_id':ref,'quote':text[start:end],'start_offset':start,'end_offset':end}
    baseline={'id':'release-chat','arm':'baseline','retrieved_source_ids':['E1'],'claims':[{'text':i.text,'citations':[citation(i.text,r) for r in i.source_ids]} for i in raw.propositions]}
    cits={c['id']:c for c in chat['citations']}
    verified={'id':'release-chat','arm':'verified','retrieved_source_ids':['E1'],'claims':[{'text':c['text'],'citations':[{'source_id':'E1','quote':cits[r]['quoted_text']} for r in c['citation_ids']]} for c in chat['claims']]}
    from backend.grounding import material_values_supported
    ablation={**baseline,'arm':'numeric_guard_only','claims':[c for c in baseline['claims'] if c['citations'] and all(r['source_id']=='E1' for r in c['citations']) and material_values_supported(c['text'],[r['quote'] for r in c['citations']])]}
    predictions=[baseline,verified,ablation];report=evaluate(dataset,predictions)
    report.update(model=model.metadata,baseline_kind='Single-pass schema-constrained RAG using the same deployed base model.',baseline_elapsed_seconds=round(time.monotonic()-started,2),frontier_baseline_tested=False,held_out_judging_data_tested=False)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for name,rows in [('dataset',dataset),('predictions',predictions)]: (args.output_dir/(name+'.jsonl')).write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows)+'\n',encoding='utf-8')
    (args.output_dir/'comparison.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps({'traceability_delta':report['traceability_delta'],'qualification_claim':report['qualification_claim']}),flush=True)


if __name__=='__main__':main()
