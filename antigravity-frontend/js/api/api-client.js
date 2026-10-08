import {createApiClient} from './transport.js';
export const generateUUID=()=>crypto.randomUUID();
const baseUrl=window.CASELENS_API_BASE || location.origin;
const documents=new Map(),citations=new Map(),tickets=new Map();
const terminal=new Set(['completed','completed_with_warnings','failed','cancelled']);
const wrap=data=>({data,meta:{api_version:'v1'}});
const transport=createApiClient({baseUrl,getToken:()=>sessionStorage.getItem('caselens.session')||''});
export const escapeHtml=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function registerEvidence(report){for(const c of report.citations||[])citations.set(c.id,c);return report;}
export async function request(path,options){
  try{return await (await transport.request(path,options)).json();}
  catch(e){e.error={message:e.message,code:e.code,field_errors:e.field_errors||[],retryable:e.retryable};throw e;}
}
export async function initializeSession(){
  if(sessionStorage.getItem('caselens.session')){
    try{await request('session');return;}catch(e){if(e.status!==401)throw e;sessionStorage.removeItem('caselens.session');}
  }
  const response=await fetch(new URL('/demo/session',baseUrl),{method:'POST',redirect:'error'});
  if(response.ok){sessionStorage.setItem('caselens.session',(await response.json()).data.token);return;}
  await new Promise(resolve=>{
    const overlay=document.createElement('div');overlay.className='modal-backdrop open';
    overlay.innerHTML='<form class="modal-card" style="padding:2rem"><h2>Connect to CaseLens</h2><p>Enter a backend session token supplied by your administrator.</p><label>Session token<input class="input" type="password" required autocomplete="off"></label><p role="alert"></p><button class="btn btn-primary">Connect</button></form>';
    document.body.append(overlay);
    overlay.querySelector('form').onsubmit=async e=>{e.preventDefault();sessionStorage.setItem('caselens.session',overlay.querySelector('input').value.trim());try{await request('session');overlay.remove();resolve();}catch(error){sessionStorage.removeItem('caselens.session');overlay.querySelector('[role=alert]').textContent=error.message;}};
  });
}
export async function download(path,name){const response=await transport.request(path);const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);}
export const LegalApiClient={
  _docName:id=>documents.get(id)?.name||id,
  _envelope:wrap,
  async home(){return request('home');},
  async listDocuments(filter={}){
    const result=[];let cursor=null;
    do{const p=new URLSearchParams({...filter,limit:'100'});if(cursor)p.set('cursor',cursor);const res=await request('documents?'+p);for(const doc of res.data.items){documents.set(doc.id,doc);if(doc.metadata?.document_type!=='user_input')result.push(doc);}cursor=res.data.next_cursor;}while(cursor);
    return wrap(result);
  },
  async getDocument(id){const res=await request('documents/'+id);documents.set(id,res.data);return res;},
  getJob:id=>request('jobs/'+id),
  cancelJob:id=>request('jobs/'+id+'/cancel',{method:'POST',body:{}}),
  async createDocumentUpload(payload){const res=await request('documents/uploads',{method:'POST',body:payload,idempotencyKey:generateUUID()});tickets.set(res.data.document_id,res.data);return res;},
  uploadFileBytes:(url,file)=>transport.request(url,{method:'PUT',body:file,raw:true,headers:{'Content-Type':file.type||mime(file.name)}}),
  completeDocumentUpload:(id,payload)=>request('documents/'+id+'/complete',{method:'POST',body:{...payload,upload_id:payload.upload_id||tickets.get(id)?.upload_id},idempotencyKey:generateUUID()}),
  async uploadDocument(file,metadata={}){
    const capabilities=(await request('documents/capabilities')).data;
    if(!capabilities.media_types.includes(file.type||mime(file.name)))throw new Error('This server does not support that file type. Use PDF or DOCX.');
    if(file.size>capabilities.max_file_bytes)throw new Error('File exceeds the 25 MB limit.');
    const job=await transport.upload(file,metadata);await this.waitJob(job.job_id);return this.getDocument(job.document_id);
  },
  async waitJob(id){for(let count=0;count<1800;count++){const res=await this.getJob(id);if(terminal.has(res.data.status)){if(['failed','cancelled'].includes(res.data.status))throw new Error(res.data.failure?.message||'Task '+res.data.status);return res;}await new Promise(r=>setTimeout(r,1000));}throw new Error('Task still running; return to Documents to check its status.');},
  async getCitation(id){
    if(citations.has(id))return wrap(citations.get(id));
    // Document inspection resolves a real stored chunk, never a fabricated citation.
    const doc=(await this.getDocument(id)).data;
    const chunk=(await request('documents/'+id+'/chunks?limit=1')).data.items[0];
    if(!chunk)throw new Error('This document has no ready text chunks.');
    return wrap({id:chunk.id,label:'Source',document_id:id,document_name:doc.name,chunk_id:chunk.id,quoted_text:chunk.text,page:chunk.page,section:chunk.section});
  },
  async getChunk(doc,id){const res=await request(`documents/${doc}/chunks/${id}`);return wrap({...res.data,document_name:documents.get(doc)?.name,quoted_text:res.data.text,surrounding_context:[res.data.previous_text,res.data.text,res.data.next_text].filter(Boolean).join('\n\n')});},
  async downloadOriginal(id){const doc=(await this.getDocument(id)).data;const chunk=(await request('documents/'+id+'/chunks?limit=1')).data.items[0];if(!chunk)throw new Error('No ready source available.');const detail=(await request(`documents/${id}/chunks/${chunk.id}`)).data;await download(detail.preview_url,doc.name);},
  subscribeJobEvents(id,onEvent,lastEventId=0){
    const controller=new AbortController();let cursor=String(lastEventId),stopped=false,deliveredTerminal=false;
    const close=()=>{stopped=true;controller.abort();};
    (async()=>{let failures=0;while(!stopped&&failures<5){try{
      for await(const evt of transport.events(id,{signal:controller.signal,lastEventId:cursor})){
        if(evt.id)cursor=evt.id;
        const data={...evt.data,final_status:evt.data.final_status||evt.data.status};
        await onEvent({...evt,id:Number(evt.id||0),data});
        if(stopped)break;
        if(evt.event==='job.snapshot'&&terminal.has(data.status)&&!deliveredTerminal){
          deliveredTerminal=true;await onEvent({event:data.status==='failed'?'job.failed':data.status==='cancelled'?'job.progress':'job.completed',id:Number(cursor)+1,data:{...data,...data.failure}});close();break;
        }
        if(['job.completed','job.failed'].includes(evt.event)||data.status==='cancelled'){deliveredTerminal=true;close();break;}
      }
      if(!stopped)throw new Error('Job stream disconnected');
    }catch(e){if(stopped||e.name==='AbortError')break;failures++;if(e.status===401||failures===5){await onEvent({event:'job.failed',data:{message:e.message,retryable:true}});close();break;}await new Promise(r=>setTimeout(r,Math.min(1000*failures,4000)));}}})();
    return {close,unsubscribe:close};
  }
};
function mime(name){return {pdf:'application/pdf',doc:'application/msword',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',txt:'text/plain',png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',tif:'image/tiff',tiff:'image/tiff'}[name.split('.').pop().toLowerCase()];}
