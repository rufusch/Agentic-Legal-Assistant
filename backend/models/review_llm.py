"""Schema-constrained server-side LLM transport for the independent review model."""
import asyncio
import json
import os
import re
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


# Plug-and-play hosted presets. Every one except Anthropic speaks the OpenAI
# chat-completions dialect; base URLs may be overridden per role.
PRESETS = {
    'openai': 'https://api.openai.com/v1',
    'gemini': 'https://generativelanguage.googleapis.com/v1beta/openai',
    'groq': 'https://api.groq.com/openai/v1',
    'openrouter': 'https://openrouter.ai/api/v1',
    'together': 'https://api.together.xyz/v1',
    'mistral': 'https://api.mistral.ai/v1',
    'deepseek': 'https://api.deepseek.com/v1',
    'anthropic': 'https://api.anthropic.com',
}
LOCAL_PROVIDERS = {'ollama', 'lmstudio', 'compatible'}
PROVIDERS = LOCAL_PROVIDERS | set(PRESETS)
ROLES = ('review', 'drafting', 'research', 'chat', 'verifier', 'baseline', 'judge', 'rerank', 'rewrite')


def _env(role, key):
    """Role-specific value, then the shared LEXIMIND_LLM_* default, then legacy REVIEW_* keys."""
    for name in (f'LEXIMIND_{role.upper()}_{key}', f'LEXIMIND_LLM_{key}', f'LEXIMIND_REVIEW_{key}'):
        value = os.getenv(name)
        if value not in (None, ''):
            return value
    return None


def _json_from_text(text):
    text = re.sub(r'<think>.*?</think>', '', text or '', flags=re.S).strip()
    fenced = re.search(r'```(?:json)?\s*(.*?)```', text, re.S)
    if fenced: text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        start = min([i for i in (text.find('{'), text.find('[')) if i >= 0], default=-1)
        if start < 0: raise
        return json.loads(text[start:text.rfind('}' if text[start] == '{' else ']') + 1])


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
    role: str = 'review'

    @classmethod
    def for_role(cls, role='review', **overrides):
        """Build a client for one workflow role from environment variables.

        LEXIMIND_<ROLE>_LLM_PROVIDER / _BASE_URL / _LLM_MODEL / _API_KEY override
        LEXIMIND_LLM_* which override legacy LEXIMIND_REVIEW_*. Hosted presets
        (openai, gemini, groq, openrouter, together, mistral, deepseek, anthropic)
        need only a model and key. Provider keys such as OPENAI_API_KEY are used
        when no LEXIMIND key is set.
        """
        provider = (_env(role, 'LLM_PROVIDER') or 'ollama').lower()
        hosted = provider in PRESETS
        explicit = os.getenv(f'LEXIMIND_{role.upper()}_BASE_URL') or os.getenv('LEXIMIND_LLM_BASE_URL')
        base_url = explicit or (PRESETS[provider] if hosted else os.getenv('LEXIMIND_REVIEW_BASE_URL') or 'http://127.0.0.1:11434')
        key = _env(role, 'API_KEY') or (os.getenv({'gemini': 'GEMINI_API_KEY'}.get(provider, provider.upper() + '_API_KEY'), '') if hosted else '')
        local_url = urlsplit(base_url).hostname in {'localhost', '127.0.0.1', '::1'} and urlsplit(base_url).scheme == 'http'
        values = dict(provider=provider, base_url=base_url, model=_env(role, 'LLM_MODEL') or 'qwen3:4b-instruct',
            deployment='cloud' if hosted or not local_url else os.getenv('LEXIMIND_MODEL_DEPLOYMENT', 'local'), api_key=key or '',
            allow_private_http=os.getenv('LEXIMIND_MODEL_ALLOW_HTTP') == '1',
            num_threads=int(os.environ['LEXIMIND_MODEL_NUM_THREADS']) if os.getenv('LEXIMIND_MODEL_NUM_THREADS') else None,
            max_output_tokens=int(os.getenv('LEXIMIND_MODEL_MAX_OUTPUT_TOKENS', '4000')),
            timeout_seconds=int(os.getenv('LEXIMIND_MODEL_TIMEOUT_SECONDS', '900')), role=role)
        values.update(overrides)
        return cls(**values)

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
        if self.deployment not in {'local','cloud'} or self.provider not in PROVIDERS or url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Invalid server-side model configuration.')
        if self.deployment=='local' and (not loopback or url.scheme!='http'):
            raise ValueError('Local deployment requires a loopback model endpoint.')
        if self.deployment=='cloud' and url.scheme=='http' and not loopback and not self.allow_private_http:
            raise ValueError('Cloud model endpoints require HTTPS; explicitly allow HTTP only on a private deployment network.')
        if not self.model or len(self.model)>200 or (self.deployment=='local' and self.model.lower().endswith(':cloud')):
            raise ValueError('Choose an explicit model appropriate for this deployment.')

    @property
    def headers(self):
        if self.provider=='anthropic':
            return {'x-api-key':self.api_key,'anthropic-version':'2023-06-01'} if self.api_key else {'anthropic-version':'2023-06-01'}
        return {'Authorization':'Bearer '+self.api_key} if self.api_key else {}

    def _url(self, endpoint):
        """endpoint is 'chat' or 'models'. Base URLs that already carry a version path are respected."""
        base=self.base_url.rstrip('/')
        if self.provider=='ollama': return base+('/api/chat' if endpoint=='chat' else '/api/tags')
        if self.provider=='anthropic': return base+('/v1/messages' if endpoint=='chat' else '/v1/models')
        prefix=base if urlsplit(base).path not in ('','/') else base+'/v1'
        return prefix+('/chat/completions' if endpoint=='chat' else '/models')

    @property
    def metadata(self):
        return {'id':'leximind-'+self.role,'workflow':self.role,'version':self.model,'kind':'local_llm' if self.deployment=='local' else 'hosted_llm','provider':self.provider,'available':True,'trainable':True,'output_schema':'review-report-v2','prompt_version':'review-reasoning-v1','verification_version':'quoted-spans-plus-model-check-v1','destination':'local machine' if self.deployment=='local' else 'configured server-side model','deployment':self.deployment}

    def status(self):
        try:
            if self.provider in PRESETS and not self.api_key:
                return {'ready':False,'reason':'MODEL_KEY_MISSING','message':f'Set an API key for the {self.provider} {self.role} model.','model':self.metadata}
            with httpx.Client(timeout=8,trust_env=False,headers=self.headers) as client:
                data=client.get(self._url('models')).raise_for_status().json()
            names=[m.get('name') or m.get('id') for m in data.get('models',data.get('data',[]))]
            ready=self.model in names or any(str(n).endswith('/'+self.model) for n in names) or (self.provider in PRESETS and bool(names))
            selected=next((m for m in data.get('models',data.get('data',[])) if (m.get('name') or m.get('id'))==self.model),{})
            return {'ready':ready,'reason':None if ready else 'MODEL_NOT_INSTALLED','message':'Model ready.' if ready else 'Download or load the selected configured model.','model':{**self.metadata,'artifact_digest':selected.get('digest')}}
        except Exception:
            return {'ready':False,'reason':'MODEL_UNAVAILABLE','message':'Check the configured model service.','model':self.metadata}

    def complete(self, messages, schema, cancelled=lambda:False):
        return asyncio.run(self._complete(messages,schema,cancelled))

    async def _complete(self,messages,schema,cancelled):
        if cancelled(): raise ReviewCancelled()
        path=self._url('chat')
        if self.provider=='ollama':
            options={'temperature':0,'num_ctx':16384,'num_predict':self.max_output_tokens}
            if self.num_threads is not None: options['num_thread']=self.num_threads
            payload={'model':self.model,'messages':messages,'format':schema,'stream':False,'options':options,'keep_alive':'10m'}
        elif self.provider=='anthropic':
            system='\n\n'.join(m['content'] for m in messages if m['role']=='system')
            payload={'model':self.model,'max_tokens':self.max_output_tokens,'temperature':0,'system':system,
                'messages':[m for m in messages if m['role']!='system'],
                'tools':[{'name':'structured_output','description':'Return the answer in this exact schema.','input_schema':schema}],
                'tool_choice':{'type':'tool','name':'structured_output'}}
        else:
            strict=os.getenv('LEXIMIND_JSON_MODE','schema')
            payload={'model':self.model,'messages':messages,'temperature':0,'max_tokens':self.max_output_tokens,'stream':False}
            if strict=='object':
                payload['messages']=messages+[{'role':'user','content':'Return only JSON matching this schema: '+json.dumps(schema)}]
                payload['response_format']={'type':'json_object'}
            else:
                payload['response_format']={'type':'json_schema','json_schema':{'name':'structured_output','strict':self.provider not in PRESETS or self.provider=='openai','schema':schema}}
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds,connect=5),trust_env=False,transport=self.transport,headers=self.headers) as client:
            async def fetch():
                # Server-configured URL; no redirects, proxies, tools or document URLs are followed.
                async with client.stream('POST',path,json=payload) as response:
                    if response.status_code==400 and self.provider not in {'ollama','anthropic'} and payload.get('response_format',{}).get('type')=='json_schema':
                        # Some compatible servers reject strict schemas; retry once in JSON-object mode.
                        await response.aread()
                        payload['response_format']={'type':'json_object'}
                        payload['messages']=messages+[{'role':'user','content':'Return only JSON matching this schema: '+json.dumps(schema)}]
                        return await fetch()
                    if response.status_code in (401,403):
                        raise ReviewModelError('MODEL_AUTH_FAILED','The configured model rejected its API key.',False)
                    if response.status_code==429:
                        raise ReviewModelError('MODEL_RATE_LIMITED','The configured model is rate limited; retry shortly.')
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
                    elif self.provider=='anthropic':
                        if data.get('stop_reason')=='max_tokens':raise ReviewModelError('MODEL_OUTPUT_LIMIT','Model output was cut off; narrow the document scope.')
                        return next(b['input'] for b in data['content'] if b.get('type')=='tool_use')
                    else:
                        choice=data['choices'][0]
                        if choice.get('finish_reason')=='length':raise ReviewModelError('MODEL_OUTPUT_LIMIT','Model output was cut off; narrow the document scope.')
                        content=choice['message']['content']
                    return _json_from_text(content)
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
