import assert from 'node:assert/strict';
import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {resolve,extname} from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(process.env.CASELENS_NODE_MODULES+'/package.json');
const {chromium}=require('playwright');
const root=resolve('hacknex2-frontend');
const server=http.createServer(async(req,res)=>{
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'");
  if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end('<main id="view" class="active"></main>');return;}
  if(req.url==='/app'){res.setHeader('Content-Type','text/html');res.end(await readFile(resolve(root,'index.html')));return;}
  try{const path=resolve(root,'.'+req.url.split('?')[0]);if(!path.startsWith(root))throw Error();res.setHeader('Content-Type',extname(path)==='.js'?'text/javascript':'text/css');res.end(await readFile(path));}catch{res.writeHead(404).end();}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let readerRequests=[];let conversationSettings=[];let researchCalls=0;let researchFail=true;let uploadFail=true;let chatFail=true;let reviewCalls=0;let draftFail=true;let generatedDraft=null;
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname;const method=route.request().method();let data={};let status=200;
  if(path.endsWith('/documents/capabilities'))data={media_types:['text/plain'],max_file_bytes:1000};
  else if(path.endsWith('/session'))data={tenant_id:'test'};
  else if(path.endsWith('/home'))data={tenant:{id:'test',display_name:'Test'},user:{display_name:'Test User'},notifications:[],recent_activity:[]};
  else if(path.endsWith('/documents/uploads')){status=uploadFail?503:201;data={document_id:'doc',upload_id:'ticket',upload_url:'/api/v1/documents/doc/bytes?token=test'};}
  else if(path.endsWith('/bytes'))data={};
  else if(path.endsWith('/complete'))data={job_id:'parse',document_id:'doc'};
  else if(path.endsWith('/jobs/parse'))data={status:'completed'};
  else if(path.endsWith('/documents/doc'))data={id:'doc',name:'source.txt',status:'ready',metadata:{},created_at:new Date().toISOString()};
  else if(path.endsWith('/documents'))data={items:[{id:'doc',name:'source.txt',status:'ready',metadata:{},created_at:new Date().toISOString()}],next_cursor:null};
  else if(path.endsWith('/research')&&method==='POST'){researchCalls++;status=researchFail?503:202;data={research_id:'memo',job_id:'research'};}
  else if(path.endsWith('/research')){status=503;}
  else if(path.endsWith('/drafts')&&method==='POST'){status=draftFail?503:202;data={draft_id:'draft',job_id:'intake'};}
  else if(path.endsWith('/drafts/draft/requirements'))data={items:[{id:'missing',key:'signature',required:false,current_answer:null,question:'Signature'}]};
  else if(path.endsWith('/drafts/draft/generate')){generatedDraft=route.request().postDataJSON();status=202;data={job_id:'generation'};}
  else if(path.endsWith('/jobs/intake/events')||path.endsWith('/jobs/generation/events')){await route.fulfill({status:200,contentType:'text/event-stream',body:'id: 1\nevent: job.completed\ndata: {"status":"completed_with_warnings"}\n\n'});return;}
  else if(path.endsWith('/drafts/draft/versions'))data={items:[{version:1,draft:{status:'completed_with_warnings'},created_at:new Date().toISOString()}]};
  else if(path.endsWith('/drafts/draft'))data={id:'draft',title:'Synthetic uploaded draft',version:1,needs_verification:false,sections:[{id:'s',heading:'Terms',blocks:[{id:'b',text:'Synthetic uploaded draft output',editable:true,claim_ids:[],citation_ids:[]}]}],warnings:[],citations:[],confidence:{score:0.5},unresolved_placeholders:[]};
  else if(path.includes('/sections/')&&method==='PATCH'){status=503;}
  else if(path.endsWith('/drafts'))data={items:[]};
  else if(path.endsWith('/reviews')&&method==='POST'){reviewCalls++;status=503;}
  else if(path.includes('/export')){await route.fulfill({status:200,contentType:'application/pdf',body:'Synthetic export'});return;}
  else if(path.endsWith('/chat/config'))data={model:{version:'Test'}};
  else if(path.endsWith('/conversations')&&method==='POST'){conversationSettings.push(route.request().postDataJSON().settings);data={conversation_id:'conversation'};}
  else if(path.endsWith('/conversations')){status=503;}
  else if(path.endsWith('/messages')&&method==='GET')data=chatFail?[]:[{id:'answer',role:'assistant',content:'Synthetic document summary',status:'completed',citations:[]}];
  else if(path.endsWith('/messages')&&method==='POST'){readerRequests.push(route.request().postDataJSON());status=chatFail?503:202;data={assistant_message_id:'answer',job_id:'reader'};}
  else if(path.endsWith('/jobs/reader'))data={status:'completed'};
  else if(path.endsWith('/grounding-audit/outputs'))data={items:[]};
  else throw Error('Unhandled API '+method+' '+path);
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(status>=400?{error:{message:'Test service unavailable',code:'UNAVAILABLE'}}:{data})});
 });
 await page.goto('http://127.0.0.1:'+server.address().port);
 await page.evaluate(()=>{window.toasts=[];window.showToast=(text)=>window.toasts.push(text);window.app={updateDocBadgeCount(){}};sessionStorage.setItem('caselens.session','test');sessionStorage.setItem('caselens.tenant','test');});
 const view=async(name)=>page.evaluate(async name=>{const module=await import('/js/views/'+name+'.js');const Class=Object.values(module).find(v=>typeof v==='function');window.view=new Class(document.querySelector('#view'),()=>{});await window.view.render();},name);
 await view('drafting');
 await page.locator('#df-submit').click();await page.getByText('Describe the draft you need in at least 5 characters.').waitFor();
 await page.locator('#df-type').fill('Test agreement');await page.locator('#df-inst').fill('Synthetic test instructions.');
 await page.locator('#df-submit').click();await page.waitForFunction(()=>window.toasts.includes('Test service unavailable'));
 await page.locator('#df-submit:not([disabled])').waitFor();assert.equal(await page.locator('#df-inst').inputValue(),'Synthetic test instructions.');
 await page.evaluate(()=>{view.requirements=[{id:'party',question:'Party',required:true,current_answer:null}];view._renderRequirements();});
 await page.locator('.req-input').fill('Example');assert.equal(await page.locator('#df-generate').isEnabled(),true);
 await page.locator('.req-input').fill('');assert.equal(await page.locator('#df-generate').isEnabled(),false);
 draftFail=false;uploadFail=false;await view('drafting');
 await page.locator('#df-upload').setInputFiles({name:'draft-source.txt',mimeType:'application/octet-stream',buffer:Buffer.from('Synthetic drafting evidence')});
 await page.getByText('Synthetic uploaded draft output').waitFor();
 assert.deepEqual(generatedDraft,{proceed_with_missing_information:true,acknowledged_requirement_ids:['missing']});
 assert.equal(await page.locator('#df-ack').count(),0);draftFail=true;uploadFail=true;
 await view('research');
 await page.locator('#res-question').fill('Synthetic research question');await page.locator('#res-jurisdiction').fill('Supreme Court');await page.locator('.doc-cb').check();
 await page.locator('#res-submit').click();await page.locator('#res-submit:not([disabled])').waitFor();assert.equal(researchCalls,1);
 await page.evaluate(()=>view.render());assert.equal(await page.locator('#res-question').inputValue(),'Synthetic research question');assert.equal(await page.locator('.doc-cb').isChecked(),true);
 let dialogs=0;page.on('filechooser',()=>dialogs++);await Promise.all([page.waitForEvent('filechooser'),page.locator('#res-upload-box').click()]);assert.equal(dialogs,1);
 uploadFail=false;await page.locator('.doc-cb').uncheck();
 await page.locator('#res-file-upload').setInputFiles({name:'research-source.txt',mimeType:'text/plain',buffer:Buffer.from('Synthetic research context')});
 await page.waitForFunction(()=>window.toasts.includes('Documents ready and selected.'));
 await page.locator('.doc-cb:checked').waitFor();assert.equal(await page.locator('#res-question').inputValue(),'Synthetic research question');
 uploadFail=true;await view('documents-hub');await page.locator('#input-search-docs').fill('" test');await page.evaluate(()=>view.render());assert.equal(await page.locator('#input-search-docs').inputValue(),'" test');
 await page.locator('#btn-open-upload-modal').click();await page.locator('#file-picker-input').setInputFiles({name:'source.txt',mimeType:'text/plain',buffer:Buffer.from('Synthetic source')});
 await page.locator('#btn-submit-upload').click();await page.getByRole('button',{name:'Retry Upload'}).waitFor();assert.equal(await page.locator('#upload-meta-title').inputValue(),'source');
 uploadFail=false;await page.getByRole('button',{name:'Retry Upload'}).click();await page.waitForFunction(()=>window.toasts.includes('Document parsed and ready'));
 await view('chat');await page.locator('#chat-input').fill('Synthetic chat question');await page.locator('#chat-send').click();await page.locator('#chat-send:not([disabled])').waitFor();assert.equal(await page.locator('#chat-input').inputValue(),'Synthetic chat question');
 await page.locator('#chat-input').press('Shift+Enter');assert.match(await page.locator('#chat-input').inputValue(),/\n/);
 await page.locator('#chat-file-input').setInputFiles({name:'chat-source.txt',mimeType:'application/octet-stream',buffer:Buffer.from('Synthetic chat source')});
 await page.waitForFunction(()=>window.toasts.includes('Documents parsed and attached.'));
 assert.equal(await page.locator('#chat-send').isEnabled(),true);
 assert.equal(await page.evaluate(()=>view.uploading),false);
 chatFail=false;const reviewsBefore=reviewCalls;await view('reader');
 await page.locator('#reader-file').setInputFiles({name:'reader.txt',mimeType:'text/plain',buffer:Buffer.from('Synthetic reader source')});
 await page.getByText('Synthetic document summary').waitFor();assert.equal(reviewCalls,reviewsBefore);assert.equal(await page.locator('#reader-file').isEnabled(),true);
 await page.locator('#reader-question').fill('What is the payment deadline?');await page.locator('#reader-ask').click();await page.locator('#reader-ask:not([disabled])').waitFor();
 assert.equal(readerRequests.at(-1).content,'What is the payment deadline?');assert.deepEqual(readerRequests.at(-1).selected_document_ids,['doc']);assert.equal(conversationSettings.at(-1).response_format,'document_answer');
 await page.locator('#reader-question').fill('Who are the parties?');await page.locator('#reader-question').press('Enter');await page.locator('#reader-ask:not([disabled])').waitFor();assert.equal(readerRequests.at(-1).content,'Who are the parties?');chatFail=true;
 await view('auditor');assert.equal(await page.locator('#audit-run').isDisabled(),true);
 await view('review');await page.locator('#rv-submit').click();await page.getByText('Select at least one ready document.').waitFor();
 await page.locator('.rv-doc-check').check();await page.locator('#rv-submit').click();await page.getByText('The review could not be started').waitFor();
 await page.evaluate(()=>{view.report={id:'report',version:1,status:'completed',created_at:new Date().toISOString(),source_document_ids:['doc'],warnings:[],options:{},confidence:{score:1,explanation:'Synthetic confidence'},risk_summary:{overall:'low',rationale:'Synthetic review output',items:[]},contradictions:[],missing_information:[],key_facts:[],relevant_evidence:[],claims:[]};view.versions=[];view.citMap={};view.claimMap={};view._renderReport();});
 await page.getByText('Synthetic review output').waitFor();await page.locator('#rv-export-toggle').click();assert.equal(await page.locator('#rv-export-menu').isVisible(),true);
 await view('drafting');await page.evaluate(()=>{view.draftData={title:'Synthetic draft',version:1,needs_verification:false,sections:[{id:'s',heading:'Test section',blocks:[{id:'b',text:'Synthetic draft output',editable:true,claim_ids:[],citation_ids:[]}]}],warnings:[],citations:[],confidence:{score:1},unresolved_placeholders:[]};view.versions=[{version:1}];view._renderEditor();});
 await page.getByText('Synthetic draft output').waitFor();await page.locator('.df-block').fill('Edited draft output');assert.equal(await page.locator('.df-block').innerText(),'Edited draft output');
 await view('research');await page.evaluate(()=>{view.researchId='memo';view.researchData={question:'Synthetic question',executive_summary:{text:'Synthetic memo output',citation_ids:[]},legal_framework:[],application_to_facts:[],limitations:['Synthetic limitation'],confidence:{level:'low',score:0.5,explanation:'Synthetic confidence'},sub_queries:[],citations:[]};view._renderCompleted();});
 await page.getByText('Synthetic memo output').waitFor();const [exported]=await Promise.all([page.waitForEvent('download'),page.locator('#res-export').click()]);assert.equal(exported.suggestedFilename(),'legal-research.pdf');
 await page.goto('http://127.0.0.1:'+server.address().port+'/app');
 await page.locator('#btn-hero-new-query').waitFor({timeout:5000}).catch(async e=>{console.log(await page.locator('body').innerText());console.log(errors);throw e;});await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
 await page.locator('#home-upload').click();await page.locator('#reader-file').waitFor({state:'attached'});
 assert.equal(await page.locator('#view-workflow-1 details').getAttribute('open'),null);
 await page.setViewportSize({width:1280,height:900});
 await page.locator('.header-search-input').fill('source');await page.locator('.header-search-input').press('Enter');await page.waitForFunction(()=>document.querySelector('#input-search-docs')?.value==='source');assert.equal(await page.locator('#input-search-docs').inputValue(),'source');
 await page.locator('[data-view="homepage"]').click();await page.locator('#input-assistant-query').fill('Synthetic homepage prompt');await page.locator('#btn-assistant-send').click();await page.locator('#chat-input').waitFor({timeout:5000}).catch(async e=>{console.log(await page.locator('body').innerText());console.log(errors);throw e;});assert.equal(await page.locator('#chat-input').inputValue(),'Synthetic homepage prompt');
 await page.evaluate(()=>{location.hash='local-report-anchor';});assert.equal(await page.evaluate(()=>window.app.currentView),'workflow-4');
 assert.deepEqual(errors,[]);console.log('Browser I/O passed: drafting/review validation and recovery, requirements, research persistence, file picker, upload retry, chat recovery/multiline input, empty auditor, review/draft/memo outputs and PDF download.');
}finally{await browser.close();await new Promise(r=>server.close(r));}

