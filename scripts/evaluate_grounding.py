"""Paired source-integrity evaluation; semantic support/usefulness need independent annotations.

Inputs are JSONL. No answerless system is awarded a perfect score. The script
never infers entailment from a valid citation or calls an LLM its own gold judge.
"""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean
from backend.grounding import material_values_supported


def load(path): return [json.loads(l) for l in Path(path).read_text(encoding='utf-8-sig').splitlines() if l.strip()]


def score(query,prediction):
    sources={s['id']:s for s in query['sources']};claims=prediction.get('claims',[])
    traced=0;invalid=0;value_errors=0;support=[];unknown=0
    for claim in claims:
        refs=claim.get('citations',[]);valid=bool(refs);quotes=[]
        for ref in refs:
            source=sources.get(ref.get('source_id'));quote=ref.get('quote','')
            okay=bool(source and quote and quote in source['text'])
            if okay and ('start_offset' in ref or 'end_offset' in ref):
                start=ref.get('start_offset');end=ref.get('end_offset')
                okay=isinstance(start,int) and isinstance(end,int) and 0<=start<end and source['text'][start:end]==quote
            invalid+=not okay;valid=valid and okay
            if okay:quotes.append(quote)
        values=material_values_supported(claim['text'],quotes);value_errors+=not values
        traced+=valid and values
        annotation=claim.get('human_supported')
        if isinstance(annotation,bool):support.append(annotation)
        else:unknown+=1
    gold=set(query.get('gold_source_ids',[]));retrieved=set(prediction.get('retrieved_source_ids',[]))
    return {'id':query['id'],'claim_count':len(claims),'traceable_claims':traced,'traceability':traced/len(claims) if claims else None,
        'invalid_citations':invalid,'material_value_failures':value_errors,'semantic_groundedness':mean(support) if support and not unknown else None,
        'unjudged_claims':unknown,'retrieval_recall':len(gold&retrieved)/len(gold) if gold else None,
        'retrieval_precision':len(gold&retrieved)/len(retrieved) if retrieved and gold else None,
        'answered':bool(claims),'answerable':query.get('answerable',True),
        'abstention_correct':not claims if not query.get('answerable',True) else None,
        'usefulness_human_score':prediction.get('usefulness_human_score')}


def evaluate(dataset,predictions,baseline='baseline',proposed='verified'):
    queries={q['id']:q for q in dataset}
    if len(queries)!=len(dataset):raise ValueError('Duplicate evaluation query IDs')
    index={}
    for p in predictions:
        key=(p['arm'],p['id'])
        if key in index or p['id'] not in queries:raise ValueError('Duplicate prediction or unknown query')
        index[key]=p
    required={(arm,qid) for arm in (baseline,proposed) for qid in queries}
    if not required<=index.keys():raise ValueError('Both arms must run on every identical query; partial comparisons are rejected')
    arms={}
    for arm in sorted({p['arm'] for p in predictions}):
        if {q for a,q in index if a==arm}!=queries.keys():raise ValueError('Ablations must use the same query set')
        rows=[score(q,index[arm,qid]) for qid,q in queries.items()]
        count=sum(r['claim_count'] for r in rows);traced=sum(r['traceable_claims'] for r in rows)
        semantic=[r['semantic_groundedness'] for r in rows if r['claim_count']]
        arms[arm]={'queries':len(rows),'claims':count,'quote_traceability':traced/count if count else None,
            'semantic_groundedness':mean(semantic) if semantic and None not in semantic else None,
            'answer_coverage':sum(r['answered'] for r in rows if r['answerable'])/max(1,sum(r['answerable'] for r in rows)),
            'invalid_citations':sum(r['invalid_citations'] for r in rows),'material_value_failures':sum(r['material_value_failures'] for r in rows),
            'mean_retrieval_recall':mean([r['retrieval_recall'] for r in rows if r['retrieval_recall'] is not None]) if any(r['retrieval_recall'] is not None for r in rows) else None,'rows':rows}
    b=arms[baseline]['quote_traceability'];p=arms[proposed]['quote_traceability']
    return {'evaluation_version':'paired-grounding-v1','dataset_sha256':hashlib.sha256(json.dumps(dataset,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        'splits':sorted({q.get('split','unspecified') for q in dataset}),'baseline_arm':baseline,'proposed_arm':proposed,'arms':arms,
        'traceability_delta':p-b if b is not None and p is not None else None,
        'qualification_claim':'Not established automatically. Strong baseline selection, held-out independence, semantic support and usefulness require independent review.',
        'limitations':['Valid source spans do not prove entailment.','Synthetic fault injection is not a real-model baseline benchmark.','Do not fine-tune or tune prompts on held-out query answers.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('dataset',type=Path);parser.add_argument('predictions',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=evaluate(load(args.dataset),load(args.predictions));args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8');print('Paired evaluation written to',args.output)


if __name__=='__main__':main()
