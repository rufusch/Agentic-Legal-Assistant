import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('./api-client.js', import.meta.url), 'utf8');
const {createApiClient, ApiError} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const calls = [];
globalThis.fetch = async (url, options) => {
  calls.push({url: String(url), options});
  assert.equal(options.headers.get('Authorization'), 'Bearer user-session');
  if (String(url).endsWith('/events')) {
    assert.equal(options.headers.get('Last-Event-ID'), '7');
    const bytes = new TextEncoder().encode('event: job.snapshot\ndata: {"status":"running"}\n\nid: 8\nevent: job.completed\ndata: {"result_id":"review"}\n\n');
    return new Response(new ReadableStream({start(controller) {controller.enqueue(bytes.slice(0, 23)); controller.enqueue(bytes.slice(23)); controller.close();}}));
  }
  if (String(url).endsWith('/bad')) return new Response(JSON.stringify({error:{code:'VALIDATION_ERROR',message:'Missing document',field_errors:[]}}), {status:400});
  if (String(url).endsWith('/uploads')) {
    const body = JSON.parse(options.body);
    assert.equal(body.content_type, 'text/plain'); assert.match(body.sha256, /^[a-f0-9]{64}$/);
    return new Response(JSON.stringify({data:{document_id:'doc',upload_id:'upload',upload_url:'/api/v1/documents/doc/bytes?token=capability'}}),{status:201});
  }
  if (options.method === 'PUT') { assert(options.body instanceof File); return new Response('{}'); }
  return new Response(JSON.stringify({data:{job_id:'job',status:'queued'}}),{status:202});
};
const api = createApiClient({baseUrl:'https://backend.example/', getToken:async ()=>'user-session'});
assert.equal((await api.upload(new File(['contract'], 'contract.txt'))).job_id, 'job');
assert.equal(calls[1].url, 'https://backend.example/api/v1/documents/doc/bytes?token=capability');
await assert.rejects(api.json('bad'), e => e instanceof ApiError && e.code==='VALIDATION_ERROR');
const frames = [];
for await (const event of api.events('job', {lastEventId:'7'})) frames.push(event);
assert.deepEqual(frames.map(f=>f.event), ['job.snapshot','job.completed']);
assert.equal(frames[1].id, '8');
await assert.rejects(api.request('/api/v1/../../outside'), /Invalid API path/);
console.log('API client checks passed: upload, 201/202 envelopes, bearer authorization, structured errors, split SSE frames and replay cursor.');
