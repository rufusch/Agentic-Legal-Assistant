import pytest
from scripts.evaluate_grounding import evaluate,score


def test_empty_answers_have_no_perfect_score_and_do_not_prove_qualification():
    q={'id':'q','sources':[{'id':'s','text':'The fee is INR 5000.'}],'gold_source_ids':['s'],'answerable':True}
    out=evaluate([q],[{'id':'q','arm':a,'claims':[],'retrieved_source_ids':[]} for a in ['baseline','verified']])
    assert out['arms']['verified']['quote_traceability'] is None
    assert out['arms']['verified']['answer_coverage']==0 and out['traceability_delta'] is None
    assert 'Not established' in out['qualification_claim']


def test_citations_do_not_imply_semantic_support_and_partial_pairs_fail():
    q={'id':'q','sources':[{'id':'s','text':'The fee is INR 5000.'}],'gold_source_ids':['s']}
    valid={'id':'q','claims':[{'text':'The fee is INR 5000.','citations':[{'source_id':'s','quote':'The fee is INR 5000.'}]}],'retrieved_source_ids':['s']}
    row=score(q,valid);assert row['traceability']==1 and row['semantic_groundedness'] is None and row['unjudged_claims']==1
    valid['claims'][0]['text']='The fee is INR 9000.'
    assert score(q,valid)['traceability']==0
    valid['claims'][0]['citations'][0]['source_id']='made-up'
    assert score(q,valid)['invalid_citations']==1
    with pytest.raises(ValueError):evaluate([q],[{**valid,'arm':'baseline'}])
