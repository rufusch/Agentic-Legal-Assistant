import assert from 'node:assert/strict';
globalThis.window={CASELENS_API_BASE:'https://backend.example'};
globalThis.location={origin:'https://frontend.example'};
globalThis.sessionStorage={getItem:key=>key==='caselens.session'?'test-token':null};
const calls=[];
const respond=data=>new Response(JSON.stringify({data}),{headers:{'Content-Type':'application/json'}});
let handler;
globalThis.fetch=async(url,options)=>{calls.push({url:String(url),options});assert.equal(options.headers.get('Authorization'),'Bearer test-token');return handler(String(url),options);};
const {LegalApiClient,registerEvidence}=await import('../js/api/api-client.js');
const {DraftingApi}=await import('../js/api/drafting-api.js');
const {ResearchApi}=await import('../js/api/research-api.js');

handler=async(url,options)=>{
  if(url.endsWith('/drafts'))return respond({draft_id:'draft',job_id:'requirements'});
  if(url.endsWith('/requirements'))return respond({items:[{id:'requirement',key:'applicant_name'}],missing_requirement_ids:['requirement']});
  if(url.includes('/sections/')){assert.equal(JSON.parse(options.body).base_version,3);return respond({version:4,needs_verification:true});}
  if(url.endsWith('/research')){const body=JSON.parse(options.body);assert.deepEqual(body.context_document_ids,['context']);assert.deepEqual(body.filters.courts,['High Court of Delhi']);assert.equal(body.jurisdiction,undefined);return respond({research_id:'memo',job_id:'research'});}
  throw new Error('Unexpected request '+url);
};
assert.equal((await DraftingApi.createDraft({document_type:'anticipatory_bail_application',jurisdiction:'IN-MH',instructions:'Test instructions'})).data.job_id,'requirements');
assert.equal((await DraftingApi.getRequirements('draft')).data[0].key,'applicant_name');
await DraftingApi.patchSection('draft','section',{text:'Edited section',base_version:3});
await ResearchApi.createResearch({question:'What does the authority say?',jurisdiction:'Delhi High Court',document_ids:['context']});

// Hash the actual file, upload authenticated bytes, complete with the issued ticket,
// and wait for parsing before making the source selectable.
let uploaded=false,completed=false;
handler=async(url,options)=>{
  if(url.endsWith('/capabilities'))return respond({media_types:['text/plain'],max_file_bytes:25*1024*1024});
  if(url.endsWith('/uploads')){const p=JSON.parse(options.body);assert.match(p.sha256,/^[a-f0-9]{64}$/);assert.equal(p.size_bytes,14);return respond({document_id:'source',upload_id:'ticket',upload_url:'/api/v1/documents/source/bytes?token=capability'});}
  if(url.includes('/bytes?')){uploaded=true;assert.equal(options.method,'PUT');assert.equal(options.headers.get('Content-Type'),'text/plain');assert.equal(await options.body.text(),'Actual source.');return respond({});}
  if(url.endsWith('/complete')){assert(uploaded);completed=true;const p=JSON.parse(options.body);assert.equal(p.upload_id,'ticket');assert.equal(p.metadata.document_type,'case');return respond({document_id:'source',job_id:'parser'});}
  if(url.endsWith('/jobs/parser')){assert(completed);return respond({status:'completed_with_warnings'});}
  if(url.endsWith('/documents/source'))return respond({id:'source',name:'matter.txt',status:'ready'});
  throw new Error('Unexpected request '+url);
};
assert.equal((await LegalApiClient.uploadDocument(new File(['Actual source.'],'matter.txt',{type:'text/plain'}),{document_type:'case'})).data.status,'ready');

// A job may finish before the view subscribes. A terminal snapshot must complete
// the view even when the original completed event is no longer replayed.
handler=async()=>new Response('event: job.snapshot\ndata: {"status":"completed_with_warnings","result_id":"draft"}\n\n',{headers:{'Content-Type':'text/event-stream'}});
await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(new Error('Terminal snapshot lost')),1500);LegalApiClient.subscribeJobEvents('late',evt=>{if(evt.event==='job.completed'){assert.equal(evt.data.final_status,'completed_with_warnings');assert(evt.id>0);clearTimeout(timeout);resolve();}});});
registerEvidence({citations:[{id:'citation-a',label:'S1',document_id:'doc-a'}]});registerEvidence({citations:[{id:'citation-b',label:'S1',document_id:'doc-b'}]});
assert.equal((await LegalApiClient.getCitation('citation-a')).data.document_id,'doc-a');
assert.equal((await LegalApiClient.getCitation('citation-b')).data.document_id,'doc-b');
handler=async()=>new Response(JSON.stringify({error:{code:'VERSION_CONFLICT',message:'Reload the draft.',field_errors:[]}}),{status:409});
await assert.rejects(()=>DraftingApi.patchSection('draft','section',{text:'stale',base_version:1}),e=>e.status===409&&e.error.code==='VERSION_CONFLICT');
const {ChatApi}=await import('../js/api/chat-api.js');
handler=async(url,options)=>{
  if(url.endsWith('/conversations/convo/messages')){
    const p=JSON.parse(options.body);assert.deepEqual(p.selected_document_ids,['source']);
    assert.equal(p.content,'What does the source establish?');
    return respond({job_id:'chat-job',assistant_message_id:'answer'});
  }
  if(url.endsWith('/feedback')){
    assert.deepEqual(JSON.parse(options.body),{accepted:true,use_for_training:false});return respond({feedback_id:'feedback'});
  }
  throw new Error('Unexpected chat request: '+url);
};
assert.equal((await ChatApi.sendMessage('convo',{content:'What does the source establish?',selected_document_ids:['source']})).data.job_id,'chat-job');
await ChatApi.feedback('convo','answer',{accepted:true,use_for_training:false});
console.log('CaseLens live-client contract tests passed, including real chat scope and training consent mapping.');
