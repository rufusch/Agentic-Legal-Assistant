'use strict';
const $ = id => document.getElementById(id);
let token = sessionStorage.getItem('hacknex-session') || '';
let documents = [], nextCursor = null, currentDoc = null, currentChunks = [], chunkCursor = null, previewUrl = null, deleting = null;
const jobs = new Map(), controllers = new Map();
const terminal = new Set(['completed', 'completed_with_warnings', 'failed', 'cancelled']);
const types = {doc:'application/msword',txt:'text/plain', pdf:'application/pdf', docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document', png:'image/png', jpg:'image/jpeg', jpeg:'image/jpeg', tif:'image/tiff', tiff:'image/tiff'};
function node(tag, cls, text) { const el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el; }
function notice(message) { $('notice').textContent = message; $('notice').classList.toggle('hidden', !message); }
function size(bytes) { return bytes < 1024*1024 ? `${(bytes/1024).toFixed(1)} KB` : `${(bytes/1024/1024).toFixed(1)} MB`; }
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {}); if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.json !== undefined) { headers.set('Content-Type','application/json'); options.body = JSON.stringify(options.json); delete options.json; }
  const response = await fetch(path, {...options, headers});
  if (!response.ok) { let body; try { body = await response.json(); } catch {} if (response.status === 401) { $('login').classList.remove('hidden'); $('connection').textContent = 'Session expired'; } throw new Error(body?.error?.message || `Request failed (${response.status})`); }
  if (options.blob) return response.blob();
  return (await response.json()).data;
}
function safe(action) { return async (...args) => { try { await action(...args); } catch (e) { notice(e.message); } }; }
async function connect(local = false) {
  if (local || !token) { const response = await fetch('/demo/session', {method:'POST'}); if (!response.ok) { $('login').classList.remove('hidden'); $('connection').textContent = 'Not connected'; return; } token = (await response.json()).data.token; }
  const session = await api('/api/v1/session'); sessionStorage.setItem('hacknex-session', token);
  $('login').classList.add('hidden'); $('connection').replaceChildren(node('i'), document.createTextNode('Backend connected'));
  $('session-label').textContent = session.mode === 'local_demo' ? 'Local demo · live API' : 'Authenticated session';
  $('retention-label').textContent = `Sources retained for ${session.retention_days} days`;
  notice(''); await refresh();
}
async function refresh(append = false) {
  const params = new URLSearchParams({limit:'25', query:$('name-filter').value});
  if ($('status-filter').value) params.set('status', $('status-filter').value);
  if (append && nextCursor) params.set('cursor', nextCursor);
  const [home, page] = await Promise.all([api('/api/v1/home'), api('/api/v1/documents?' + params)]);
  const counts = home.document_counts;
  $('stat-total').textContent = Object.values(counts).reduce((a,b)=>a+b,0); $('stat-ready').textContent = counts.ready;
  $('stat-processing').textContent = counts.processing + counts.uploading; $('stat-failed').textContent = counts.failed;
  $('nav-count').textContent = $('stat-total').textContent; $('storage-label').textContent = `${size(home.storage_bytes)} stored`;
  documents = append ? [...documents, ...page.items] : page.items; nextCursor = page.next_cursor;
  $('more-documents').classList.toggle('hidden', !nextCursor); $('list-count').textContent = documents.length;
  renderDocuments();
  await Promise.all(documents.slice(0,8).filter(doc=>doc.job_id && doc.status!=='processing' && !jobs.has(doc.job_id)).map(async doc=>{
    try { const job=await api(`/api/v1/jobs/${doc.job_id}`); jobs.set(doc.job_id,{...job,name:doc.name,message:job.status==='completed'?'Ready to use':job.status==='completed_with_warnings'?'Ready — check source warnings':job.failure?.message || job.status}); } catch {}
  }));
  if(jobs.size) renderActivity();
  for (const doc of documents) if (doc.status === 'processing' && doc.job_id && !controllers.has(doc.job_id)) watchJob(doc.job_id, doc.name);
}
function renderDocuments() {
  const rows = $('document-rows'); rows.replaceChildren(); $('empty-library').classList.toggle('hidden', documents.length > 0);
  for (const doc of documents) {
    const row = node('tr'), title = node('td'), identity = node('div','document-name');
    identity.append(node('span','file-icon',doc.name.split('.').pop().toUpperCase())); const text = node('div','',doc.name);
    text.append(node('small','',`${size(doc.size_bytes)}${doc.metadata.jurisdiction ? ' · '+doc.metadata.jurisdiction : ''}${doc.deduplicated_from ? ' · duplicate source' : ''}`)); identity.append(text); title.append(identity); row.append(title);
    const status = node('td'), badge = node('span',`badge ${doc.status}`, doc.status === 'failed' ? (doc.failure?.code === 'CANCELLED' ? 'Cancelled' : 'Needs attention') : doc.status === 'ready' && doc.warnings?.length ? 'Ready · warnings' : doc.status[0].toUpperCase()+doc.status.slice(1)); status.append(badge); row.append(status);
    row.append(node('td','',doc.status === 'ready' ? `${doc.page_count ? doc.page_count+' page'+(doc.page_count===1?'':'s')+' · ' : ''}${doc.chunk_count || 0} passage${doc.chunk_count===1?'':'s'}${doc.ocr_used ? ' · OCR' : ''}` : doc.failure?.message || doc.processing.stage));
    row.append(node('td','',new Date(doc.created_at).toLocaleDateString(undefined,{month:'short',day:'numeric'})));
    const actions = node('td'), group = node('div','row-actions');
    if (doc.status === 'ready') { const view = node('button','','View source ↗'); view.onclick = safe(()=>openDocument(doc)); group.append(view); }
    if (doc.status === 'failed') { const retry = node('button','','Retry'); retry.onclick = safe(async()=>{ const result = await api(`/api/v1/documents/${doc.id}/retry`,{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()}}); watchJob(result.job_id,doc.name); await refresh(); }); group.append(retry); }
    if (doc.status === 'processing') { const cancel = node('button','','Cancel'); cancel.onclick = safe(()=>cancelJob(doc.job_id)); group.append(cancel); }
    const remove = node('button','delete','×'); remove.setAttribute('aria-label',`Delete ${doc.name}`); remove.onclick=()=>{deleting=doc; $('delete-description').textContent=doc.name; $('delete-dialog').showModal();}; group.append(remove); actions.append(group); row.append(actions); rows.append(row);
  }
}
async function uploadFile(file, metadata = null) {
  const mediaType = types[file.name.split('.').pop().toLowerCase()];
  if (!mediaType) throw new Error(`Unsupported file: ${file.name}`);
  if (!file.size || file.size > 25*1024*1024) throw new Error(`${file.name}: choose a file between 1 byte and 25 MB.`);
  const bytes = await file.arrayBuffer(), digest = await crypto.subtle.digest('SHA-256',bytes);
  const sha256 = [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('');
  const key = crypto.randomUUID();
  const upload = await api('/api/v1/documents/uploads',{method:'POST',headers:{'Idempotency-Key':key},json:{file_name:file.name,content_type:mediaType,size_bytes:file.size,sha256}});
  await api(upload.upload_url,{method:'PUT',headers:{'Content-Type':mediaType},body:bytes});
  const result = await api(`/api/v1/documents/${upload.document_id}/complete`,{method:'POST',headers:{'Idempotency-Key':key+'-complete'},json:{upload_id:upload.upload_id,metadata:metadata || {jurisdiction:$('jurisdiction').value.trim(),document_type:$('document-type').value}}});
  watchJob(result.job_id,file.name); await refresh();
  return {document_id:upload.document_id,job_id:result.job_id};
}
async function uploadFiles(files) { notice(''); for (const file of files) { try { await uploadFile(file); } catch(e) { notice(e.message); } } $('file-input').value=''; }
function renderActivity() {
  const target=$('activity'); target.replaceChildren();
  for (const [id, job] of [...jobs].sort((a,b)=>new Date(b[1].created_at || 0)-new Date(a[1].created_at || 0)).slice(0,8)) {
    const item=node('div','activity-item'), meta=node('div','activity-meta'); item.append(node('div','activity-name',job.name));
    meta.append(node('span','',job.message || job.status.replaceAll('_',' ')));
    if (!terminal.has(job.status)) { const cancel=node('button','','Cancel'); cancel.onclick=safe(()=>cancelJob(id)); meta.append(cancel); }
    else meta.append(node('span','',job.status==='completed'?'✓':job.status==='completed_with_warnings'?'⚠':'–'));
    item.append(meta); const bar=node('progress'); bar.max=1; bar.value=job.progress || 0; bar.setAttribute('aria-label',`${job.name} progress`); item.append(bar); target.append(item);
  }
}
async function cancelJob(id) { await api(`/api/v1/jobs/${id}/cancel`,{method:'POST'}); await refresh(); }
async function watchJob(id,name) {
  if (controllers.has(id)) return;
  const controller=new AbortController(); controllers.set(id,controller); let last=0, delay=500;
  jobs.set(id,{name,status:'queued',progress:0,created_at:new Date().toISOString(),message:'Connecting to progress stream'}); renderActivity();
  try {
    while (!controller.signal.aborted) {
      try {
        const response=await fetch(`/api/v1/jobs/${id}/events`,{headers:{Authorization:`Bearer ${token}`,'Last-Event-ID':String(last)},signal:controller.signal});
        if (!response.ok) throw new Error(`Progress stream unavailable (${response.status})`);
        const reader=response.body.getReader(), decoder=new TextDecoder(); let buffer='';
        while (true) {
          const {value,done}=await reader.read(); if(done) break; buffer+=decoder.decode(value,{stream:true}); buffer=buffer.replaceAll('\r\n','\n');
          let end;
          while ((end=buffer.indexOf('\n\n'))!==-1) {
            const frame=buffer.slice(0,end); buffer=buffer.slice(end+2); let event='',data='',sequence=0;
            for(const line of frame.split('\n')) { if(line.startsWith('event:')) event=line.slice(6).trim(); if(line.startsWith('data:')) data+=line.slice(5).trim(); if(line.startsWith('id:')) sequence=Number(line.slice(3).trim()); }
            if (!data || event==='heartbeat' || (sequence && sequence<=last)) continue;
            if(sequence) last=sequence; const update=JSON.parse(data), previous=jobs.get(id);
            if(event==='warning.created') continue;
            const status=event==='job.failed'?'failed':update.status || previous.status;
            if(terminal.has(previous.status) && !terminal.has(status)) continue;
            jobs.set(id,{...previous,...update,name,status,progress:event==='job.completed'?1:(update.progress ?? previous.progress),message:event==='job.failed'?update.message:event==='job.completed'?(status==='completed_with_warnings'?'Ready — check source warnings':'Ready to use'):update.message || status.replaceAll('_',' ')}); renderActivity();
          }
        }
        if(terminal.has(jobs.get(id).status)) { await refresh(); break; }
      } catch(e) { if(controller.signal.aborted) break; jobs.get(id).message='Reconnecting to processing updates…'; renderActivity(); }
      // Poll only as a fallback; the durable stream resumes from the last event ID.
      try { const snapshot=await api(`/api/v1/jobs/${id}`); if(terminal.has(snapshot.status)) { jobs.set(id,{...jobs.get(id),...snapshot}); renderActivity(); await refresh(); break; } } catch(e) { notice(e.message); break; }
      await new Promise(resolve=>setTimeout(resolve,delay)); delay=Math.min(delay*2,8000);
    }
  } finally { controllers.delete(id); }
}
async function openDocument(doc,chunkId=null) {
  currentDoc=doc; currentChunks=[]; previewUrl=null; $('source-title').textContent=doc.name; $('source-text').textContent='Loading source…'; $('source-warnings').replaceChildren();
  for(const w of doc.warnings || []) $('source-warnings').append(node('div','notice',`${w.title}: ${w.message}`));
  if(!$('source-dialog').open) $('source-dialog').showModal();
  await loadChunks();
  if(chunkId && !currentChunks.some(c=>c.id===chunkId)) { const chunk=await api(`/api/v1/documents/${doc.id}/chunks/${chunkId}`); currentChunks.push(chunk); renderChunkOptions(); }
  if(chunkId) $('chunk-select').value=chunkId;
  await showChunk();
}
function renderChunkOptions() { const select=$('chunk-select'); select.replaceChildren(); for(const [i,c] of currentChunks.entries()) { const option=node('option','',`${c.page ? 'Page '+c.page : 'Document'} · Passage ${i+1}${c.section ? ' · '+c.section.slice(0,35) : ''}`); option.value=c.id; select.append(option); } }
async function loadChunks() { const selected=$('chunk-select').value; const result=await api(`/api/v1/documents/${currentDoc.id}/chunks?limit=25${chunkCursor && currentChunks.length ? '&cursor='+chunkCursor : ''}`); currentChunks.push(...result.items); chunkCursor=result.next_cursor; renderChunkOptions(); if(selected && currentChunks.some(c=>c.id===selected)) $('chunk-select').value=selected; $('load-chunks').classList.toggle('hidden',!chunkCursor); }
async function showChunk() { const id=$('chunk-select').value; if(!id){$('source-text').textContent='No readable source passages.';return;} const c=await api(`/api/v1/documents/${currentDoc.id}/chunks/${id}`); previewUrl=c.preview_url; $('source-text').textContent=c.text; $('source-anchor').textContent=`${c.page?'Page '+c.page:'Document body'} · Characters ${c.start_offset}–${c.end_offset}${c.section?' · '+c.section:''}`; $('source-context').textContent=[c.previous_text,c.next_text].filter(Boolean).join('\n\n────\n\n') || 'No neighboring passages.'; }
function view(name) { $('library-view').classList.toggle('hidden',name!=='library'); $('search-view').classList.toggle('hidden',name!=='search'); $('nav-library').classList.toggle('active',name==='library'); $('nav-search').classList.toggle('active',name==='search'); $('breadcrumb').textContent=name==='library'?'Document library':'Source search'; }
$('nav-library').onclick=()=>view('library'); $('nav-search').onclick=()=>{view('search');$('source-query').focus();};
$('file-input').onchange=()=>uploadFiles($('file-input').files);
for(const event of ['dragenter','dragover']) $('dropzone').addEventListener(event,e=>{e.preventDefault();$('dropzone').classList.add('dragover');});
for(const event of ['dragleave','drop']) $('dropzone').addEventListener(event,e=>{e.preventDefault();$('dropzone').classList.remove('dragover');});
$('dropzone').addEventListener('drop',e=>uploadFiles(e.dataTransfer.files));
$('refresh').onclick=safe(()=>refresh()); $('more-documents').onclick=safe(()=>refresh(true)); $('status-filter').onchange=safe(()=>refresh());
let filterTimer; $('name-filter').oninput=()=>{clearTimeout(filterTimer);filterTimer=setTimeout(safe(()=>refresh()),250);};
$('local-connect').onclick=safe(()=>connect(true)); $('login-form').onsubmit=safe(async e=>{e.preventDefault();token=$('token').value.trim();await connect();$('token').value='';});
$('signout').onclick=safe(async()=>{await api('/api/v1/session/revoke',{method:'POST'});for(const c of controllers.values())c.abort();token='';sessionStorage.removeItem('hacknex-session');documents=[];jobs.clear();renderDocuments();renderActivity();$('search-results').replaceChildren();for(const id of ['stat-total','stat-ready','stat-processing','stat-failed','nav-count','list-count'])$(id).textContent='0';$('source-dialog').close();$('login').classList.remove('hidden');$('connection').textContent='Signed out';});
$('sample-button').onclick=safe(async()=>{const button=$('sample-button');button.disabled=true;button.textContent='Adding sample sources…';try{for(const name of ['service-agreement.txt','payment-amendment.txt','scanned-annexure.pdf']){const response=await fetch('/static/samples/'+name);if(!response.ok)throw new Error('Sample unavailable.');await uploadFile(new File([await response.blob()],name,{type:types[name.split('.').pop()]}));}notice('Sample documents added. Compare payment dates in Source search, and open the scanned annexure to inspect OCR.');}finally{button.disabled=false;button.textContent='Try sample documents ↗';}});
$('close-source').onclick=()=>$('source-dialog').close(); $('chunk-select').onchange=safe(showChunk); $('load-chunks').onclick=safe(loadChunks);
$('original-button').onclick=safe(async()=>{await showChunk();if(!previewUrl)return;const blob=await api(previewUrl,{blob:true});const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=currentDoc.name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);});
$('keep-document').onclick=()=>$('delete-dialog').close(); $('confirm-delete').onclick=safe(async()=>{await api(`/api/v1/documents/${deleting.id}`,{method:'DELETE'});if(deleting.job_id)controllers.get(deleting.job_id)?.abort();$('delete-dialog').close();deleting=null;await refresh();});
$('source-search').onsubmit=safe(async e=>{e.preventDefault();const button=$('search-submit');button.disabled=true;button.textContent='Finding passages…';try{const result=await api('/api/v1/documents/search',{method:'POST',json:{query:$('source-query').value}});const target=$('search-results');target.replaceChildren();if(!result.items.length)target.append(node('p','muted-text','No matching source passages. Try a different phrase or add a document.'));for(const hit of result.items){const c=hit.citation,card=node('button','search-result');card.append(node('div','',`[${c.label}] ${c.document_name}${c.page?' · Page '+c.page:''}`),node('p','',c.quoted_text),node('small','','Open exact source passage ↗'));card.onclick=safe(async()=>{const doc=await api(`/api/v1/documents/${c.document_id}`);await openDocument(doc,c.chunk_id);});target.append(card);}}finally{button.disabled=false;button.textContent='Search sources ↗';}});
safe(connect)();
