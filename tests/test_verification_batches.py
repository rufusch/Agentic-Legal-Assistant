import json
from uuid import uuid4
import pytest
from backend.verification_batches import verify_batches
from backend.research_schema import Checks
from backend.models.review_llm import ReviewModelError, LocalReviewLLM


def test_batches_cover_every_item_and_bound_output():
    items=[{'id':str(uuid4()),'text':str(n)} for n in range(13)]
    calls=[]
    class Model:
        def complete(self,messages,schema,cancelled):
            batch=json.loads(messages[-1]['content'])['items'];calls.append(batch)
            assert schema['properties']['decisions']['maxItems']==len(batch)
            return {'decisions':[{'id':i['id'],'supported':True,'reason':'Supported'} for i in batch]}
    result=verify_batches(Model(),Checks,'Check',items,lambda batch:{'items':batch},lambda:False)
    assert [len(c) for c in calls]==[5,5,3]
    assert [str(d.id) for d in result.decisions]==[i['id'] for i in items]


def test_batch_rejects_a_missing_decision():
    class Model:
        def complete(self,*args):return {'decisions':[]}
    with pytest.raises(ReviewModelError,match='omitted or duplicated'):
        verify_batches(Model(),Checks,'Check',[{'id':str(uuid4())}],lambda batch:{'items':batch},lambda:False)


def test_drafting_output_budget_can_exceed_chat_budget(monkeypatch):
    monkeypatch.setenv('LEXIMIND_MODEL_MAX_OUTPUT_TOKENS','4000')
    monkeypatch.setenv('LEXIMIND_DRAFTING_MAX_OUTPUT_TOKENS','6000')
    assert LocalReviewLLM.for_role('drafting').max_output_tokens==6000
    assert LocalReviewLLM.for_role('chat').max_output_tokens==4000
