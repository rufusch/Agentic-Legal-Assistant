"""Schema-constrained server-side LLM transport for the independent review model."""
import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx


class ReviewModelError(Exception):
    def __init__(self, code, message, retryable=True):
        self.code, self.message, self.retryable = code, message, retryable
        super().__init__(message)


class ReviewCancelled(Exception): pass


def verification_schema(model, items):
    """Bound a verification pass to exactly the supplied identifiers."""
    schema=model.model_json_schema()
    decisions=schema['properties']['decisions']
    decisions.update(minItems=len(items),maxItems=len(items))
    ref=decisions['items'].get('$ref')
    if ref:
        decision=schema['$defs'][ref.rsplit('/',1)[-1]]
        decision['properties']['id']={'type':'string','enum':[str(i['id']) for i in items]}
    return schema


@dataclass(frozen=True)
class LocalReviewLLM:
    provider: str = 'ollama'
    base_url: str = 'http://127.0.0.1:11434'
    model: str = 'qwen3:4b-instruct'
    timeout_seconds: int = 900
    transport: object = None
    deployment: str = "local"
    api_key: str = field(default="", repr=False)
    allow_private_http: bool = False
    num_threads: int | None = None
    max_output_tokens: int = 4000

    @classmethod
    def from_env(cls):
        return cls(provider=os.getenv('LEXIMIND_REVIEW_LLM_PROVIDER','ollama'),base_url=os.getenv('LEXIMIND_REVIEW_BASE_URL','http://127.0.0.1:11434'),model=os.getenv('LEXIMIND_REVIEW_LLM_MODEL','qwen3:4b-instruct'),deployment=os.getenv('LEXIMIND_MODEL_DEPLOYMENT','local'),api_key=os.getenv('LEXIMIND_REVIEW_API_KEY',''),allow_private_http=os.getenv('LEXIMIND_MODEL_ALLOW_HTTP')=='1',num_threads=int(os.environ['LEXIMIND_MODEL_NUM_THREADS']) if os.getenv('LEXIMIND_MODEL_NUM_THREADS') else None,max_output_tokens=int(os.getenv('LEXIMIND_MODEL_MAX_OUTPUT_TOKENS','4000')))

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if self.num_threads is not None and not 1 <= self.num_threads <= 256:
            raise ValueError('Model thread override must be between 1 and 256.')
        if not 256 <= self.max_output_tokens <= 16000:
            raise ValueError('Model output budget must be between 256 and 16000 tokens.')
        loopback = url.hostname in {'localhost','127.0.0.1','::1'}
        if self.deployment not in {'local','cloud'} or self.provider not in {'ollama','lmstudio','compatible'} or url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Invalid server-side model configuration.')
        if self.deployment=='local' and (not loopback or url.scheme!='http'):
            raise ValueError('Local deployment requires a loopback model endpoint.')
        if self.deployment=='cloud' and url.scheme=='http' and not loopback and not self.allow_private_http:
            raise ValueError('Cloud model endpoints require HTTPS; explicitly allow HTTP only on a private deployment network.')
        if not self.model or len(self.model)>200 or (self.deployment=='local' and 'cloud' in self.model.lower()):
            raise ValueError('Choose an explicit model appropriate for this deployment.')

    @property
    def headers(self):
        return {'Authorization':'Bearer '+self.api_key} if self.api_key else {}

    @property
    def metadata(self):
        return {'id':'leximind-review','workflow':'review','version':self.model,'kind':'local_llm' if self.deployment=='local' else 'hosted_llm','provider':self.provider,'available':True,'trainable':True,'output_schema':'review-report-v2','prompt_version':'review-reasoning-v1','verification_version':'quoted-spans-plus-model-check-v1','destination':'local machine' if self.deployment=='local' else 'configured server-side model','deployment':self.deployment}

    def status(self):
        try:
            with httpx.Client(timeout=5,trust_env=False,headers=self.headers) as client:
                path='/api/tags' if self.provider=='ollama' else '/v1/models'
                data=client.get(self.base_url.rstrip('/')+path).raise_for_status().json()
            names=[m.get('name') or m.get('id') for m in data.get('models',data.get('data',[]))]
            ready=self.model in names
            selected=next((m for m in data.get('models',data.get('data',[])) if (m.get('name') or m.get('id'))==self.model),{})
            return {'ready':ready,'reason':None if ready else 'MODEL_NOT_INSTALLED','message':'Model ready.' if ready else 'Download or load the selected configured model.','model':{**self.metadata,'artifact_digest':selected.get('digest')}}
        except Exception:
            return {'ready':False,'reason':'MODEL_UNAVAILABLE','message':'Check the configured model service.','model':self.metadata}

    def complete(self, messages, schema, cancelled=lambda:False):
        return asyncio.run(self._complete(messages,schema,cancelled))

    async def _complete(self,messages,schema,cancelled):
        if cancelled(): raise ReviewCancelled()
        if self.provider=='ollama':
            path='/api/chat'
            options={'temperature':0,'num_ctx':16384,'num_predict':self.max_output_tokens}
            if self.num_threads is not None: options['num_thread']=self.num_threads
            payload={'model':self.model,'messages':messages,'format':schema,'stream':False,'options':options,'keep_alive':'10m'}
        else:
            path='/v1/chat/completions'
            payload={'model':self.model,'messages':messages,'response_format':{'type':'json_schema','json_schema':{'name':'review_output','strict':True,'schema':schema}},'temperature':0,'max_tokens':self.max_output_tokens,'stream':False}
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds,connect=5),trust_env=False,transport=self.transport,headers=self.headers) as client:
            async def fetch():
                # Server-configured URL; no redirects, proxies, tools or document URLs are followed.
                async with client.stream('POST',self.base_url.rstrip('/')+path,json=payload) as response:
                    if response.status_code != 200:
                        code='MODEL_NOT_INSTALLED' if response.status_code==404 else 'MODEL_UNAVAILABLE'
                        raise ReviewModelError(code,'Model request failed. Check the model server and selected model.')
                    raw=bytearray()
                    async for block in response.aiter_bytes():
                        raw.extend(block)
                        if len(raw)>2*1024*1024: raise ReviewModelError('MODEL_OUTPUT_LIMIT','Model response exceeded the safe output limit.')
                    data=json.loads(raw)
                    if self.provider=='ollama':
                        if data.get('done_reason')=='length':raise ReviewModelError('MODEL_OUTPUT_LIMIT','Model output was cut off; narrow the document scope.')
                        content=data['message']['content']
                    else:
                        choice=data['choices'][0]
                        if choice.get('finish_reason')=='length':raise ReviewModelError('MODEL_OUTPUT_LIMIT','Model output was cut off; narrow the document scope.')
                        content=choice['message']['content']
                    return json.loads(content)
            task=asyncio.create_task(fetch())
            started=time.monotonic()
            try:
                while not task.done():
                    if cancelled(): raise ReviewCancelled()
                    if time.monotonic()-started>self.timeout_seconds: raise ReviewModelError('MODEL_TIMEOUT','Local analysis timed out. Use a smaller scope or faster configured model.')
                    await asyncio.wait({task},timeout=.2)
                return await task
            except httpx.TimeoutException:
                raise ReviewModelError('MODEL_TIMEOUT','Model inference timed out. Narrow the source scope or configure a faster model server.') from None
            except (httpx.HTTPError,OSError):
                raise ReviewModelError('MODEL_UNAVAILABLE','Cannot reach the configured model. Start Ollama or LM Studio and load the configured model.') from None
            except (ValueError,KeyError,TypeError,IndexError):
                raise ReviewModelError('MODEL_INVALID_OUTPUT','Model returned an invalid structured response. Retry the review.') from None
            finally:
                if not task.done():
                    task.cancel()
                    try: await task
                    except asyncio.CancelledError: pass
