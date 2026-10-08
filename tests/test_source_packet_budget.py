import json
from types import SimpleNamespace
from backend.context_budget import source_budget
from backend.models.review_llm import compact_source_metadata
from backend.models.review_llm import LocalReviewLLM,ReviewModelError
import httpx
import pytest


def test_compaction_is_lossless_for_source_text_ids_and_metadata():
    sources=[{'source_id':f'E{i}','text':'Exact quoted evidence. '+str(i),'document_name':'An official statute.pdf',
              'document_type':'statute','jurisdiction':'IN','user_provided':False} for i in range(20)]
    messages=[{'role':'system','content':'Keep instructions.'},{'role':'user','content':json.dumps({'sources':sources})}]
    compact=compact_source_metadata(messages)
    data=json.loads(compact[1]['content'])
    restored=[{**data['source_documents'][s['document_ref']],**{k:v for k,v in s.items() if k!='document_ref'}} for s in data['sources']]
    assert restored==sources and compact[0]==messages[0]
    assert len(compact[1]['content'])<len(messages[1]['content'])


def test_groq_budget_is_bounded_and_explicit_override_is_respected(monkeypatch):
    monkeypatch.delenv('LEXIMIND_SOURCE_CONTEXT_CHARACTERS',raising=False)
    assert source_budget(SimpleNamespace(provider='groq'),24000)==6000
    assert source_budget(SimpleNamespace(provider='ollama'),24000)==24000
    monkeypatch.setenv('LEXIMIND_SOURCE_CONTEXT_CHARACTERS','3600')
    assert source_budget(SimpleNamespace(provider='groq'),24000)==3600


def test_groq_transient_retry_after_and_daily_quota_are_distinct():
    calls=[]
    def transient(request):
        calls.append(request)
        if len(calls)==1:return httpx.Response(429,headers={'retry-after':'0.01'},json={'error':{'message':'Tokens per minute'}})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]})
    model=LocalReviewLLM(provider='groq',deployment='cloud',base_url='https://api.groq.com',model='m',api_key='test',transport=httpx.MockTransport(transient))
    assert model.complete([{'role':'user','content':'q'}],{'type':'object'})=={'ok':True} and len(calls)==2
    daily=[]
    def exhausted(request):
        daily.append(request);return httpx.Response(429,headers={'retry-after':'0.01'},json={'error':{'message':'tokens per day exhausted'}})
    model=LocalReviewLLM(provider='groq',deployment='cloud',base_url='https://api.groq.com',model='m',api_key='test',transport=httpx.MockTransport(exhausted))
    with pytest.raises(ReviewModelError) as error:model.complete([{'role':'user','content':'q'}],{'type':'object'})
    assert error.value.code=='MODEL_QUOTA_EXHAUSTED' and len(daily)==1


def test_verifier_retains_enough_output_room_for_structured_decisions(monkeypatch):
    monkeypatch.setenv('LEXIMIND_LLM_PROVIDER','groq')
    monkeypatch.delenv('LEXIMIND_MODEL_MAX_OUTPUT_TOKENS',raising=False)
    assert LocalReviewLLM.for_role('research').max_output_tokens==1500
    assert LocalReviewLLM.for_role('verifier').max_output_tokens==4000
