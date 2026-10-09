import {LegalApiClient,escapeHtml} from '../api/api-client.js';
import {ChatApi} from '../api/chat-api.js';
import {CitationDrawer} from '../components/citation-drawer.js';

const SUMMARY='Summarize this document in plain language. Explain its purpose, the main people or parties, important facts or terms, amounts, dates and next steps that are explicitly stated. Do not perform a risk audit or invent legal advice.';
export class ReaderView {
  constructor(el){this.el=el;this.busy=false;this.documentId=null;this.result=null;this.question='';this.error='';}
  async render(){
    const docs=(await LegalApiClient.listDocuments()).data.filter(d=>d.status==='ready');
    this.el.innerHTML=`<div class="view-header"><div><h1>Read a document</h1><p class="view-subtitle">Upload a file and get a plain-language summary. No audit or setup checklist.</p></div></div>
      <section class="card"><label for="reader-file">Upload a document</label><input class="input" id="reader-file" type="file" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.tif,.tiff">
      <p class="rv-help">PDF, DOCX, TXT or scanned images · up to 25 MB. Your summary starts once the file is ready.</p>
      <details class="simple-options"><summary>Use a saved document</summary><select class="select" id="reader-saved"><option value="">Choose a document</option>${docs.map(d=>`<option value="${escapeHtml(d.id)}" ${d.id===this.documentId?'selected':''}>${escapeHtml(d.name)}</option>`).join('')}</select><button class="btn btn-secondary" id="reader-read">Read document</button></details>
      <label for="reader-question">Anything specific? (optional)</label><input class="input" id="reader-question" value="${escapeHtml(this.question)}" placeholder="Leave blank for a summary, or ask a question"><button class="btn btn-primary" id="reader-ask">Ask question</button><p class="rv-help">Ask about your uploaded document, then click Ask question or press Enter.</p>
      <p id="reader-status" role="status" aria-live="polite"></p><p id="reader-error" role="alert">${escapeHtml(this.error)}</p><button class="btn btn-secondary" id="reader-retry" ${this.error&&this.documentId?'':'hidden'}>Try again</button></section>
      <section class="card" id="reader-result" ${this.result?'':'hidden'}></section>`;
    this.el.querySelector('#reader-question').oninput=e=>{this.question=e.target.value;};
    const submitQuestion=()=>{if(this.busy)return;const saved=this.el.querySelector('#reader-saved').value;if(saved)this.documentId=saved;if(!this.documentId){this._fail(new Error('Upload a document or choose a saved document first.'));return;}if(!this.question.trim()){this._fail(new Error('Enter a question first.'));return;}return this._answer();};
    this.el.querySelector('#reader-ask').onclick=submitQuestion;
    this.el.querySelector('#reader-question').onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();submitQuestion();}};
    this.el.querySelector('#reader-file').onchange=async e=>{
      const file=e.target.files[0];if(!file||this.busy)return;
      this._busy(true,'Reading your file…');this.error='';
      try{const doc=(await LegalApiClient.uploadDocument(file,{title:file.name,document_type:'other',jurisdiction:'IN'})).data;this.documentId=doc.id;this.el.querySelector('#reader-saved').value='';window.app?.updateDocBadgeCount();await this._answer();}
      catch(error){this._fail(error);}finally{e.target.value='';}
    };
    this.el.querySelector('#reader-read').onclick=async()=>{if(this.busy)return;const id=this.el.querySelector('#reader-saved').value;if(!id){this._fail(new Error('Choose a saved document first.'));return;}this.documentId=id;await this._answer();};
    this.el.querySelector('#reader-retry').onclick=()=>this._answer();
    this._busy(this.busy,this.status||'');if(this.result)this._result();
  }
  _busy(value,status){this.busy=value;this.status=status;this.el.querySelector('#reader-status').textContent=status;for(const id of ['reader-file','reader-read','reader-saved','reader-question','reader-ask','reader-retry'])this.el.querySelector('#'+id).disabled=value;}
  _fail(error){this.error=error.message||'Could not read the document. Try again.';this.el.querySelector('#reader-error').textContent=this.error;this.el.querySelector('#reader-retry').hidden=!this.documentId;this._busy(false,'');}
  async _answer(){
    this.answerQuestion=this.question.trim();
    this._busy(true,'Preparing your answer…');this.el.querySelector('#reader-error').textContent='';this.el.querySelector('#reader-retry').hidden=true;this.result=null;this.el.querySelector('#reader-result').hidden=true;
    try{
      const convo=(await ChatApi.createConversation({title:'Document summary',document_ids:[this.documentId],settings:{include_official_sources:true,response_format:this.question.trim()?'document_answer':'document_summary'}})).data;
      const sent=(await ChatApi.sendMessage(convo.conversation_id,{content:this.question.trim()||SUMMARY,selected_document_ids:[this.documentId]})).data;
      await LegalApiClient.waitJob(sent.job_id);
      this.result=(await ChatApi.getMessages(convo.conversation_id)).data.find(m=>m.id===sent.assistant_message_id);
      if(!this.result)throw new Error('The answer is not available yet. Try again.');
      this._busy(false,'Done.');this._result();
    }catch(error){this._fail(error);}
  }
  _result(){
    const panel=this.el.querySelector('#reader-result');panel.hidden=false;
    const sources=this.result.legal_sources||[], evidence=this.result.document_evidence||this.result.citations||[];
    const buttons=items=>items.map(c=>`<button class="btn btn-secondary" data-source="${escapeHtml(c.id)}">${escapeHtml(c.label)} · ${escapeHtml(c.document_name)}</button>`).join('');
    panel.innerHTML=`<h2>${this.answerQuestion?'Your answer':'Document summary'}</h2><p class="reader-answer">${escapeHtml(this.result.content)}</p><h3>Laws and rules used</h3>${this.result.legal_context?`<p>${escapeHtml(this.result.legal_context)}</p>`:''}${buttons(sources)}${[...new Map(sources.map(c=>[c.document_id,c])).values()].map(c=>`<p><a href="${escapeHtml(c.source_url)}" target="_blank" rel="noopener noreferrer">Open official government source</a>${c.snapshot_date?` · Snapshot: ${escapeHtml(c.snapshot_date)}`:''}</p>`).join('')}${sources.length?'':'<p class="rv-help">No relevant law or rule could be verified from the available official government sources for this summary.</p>'}<details><summary>Passages from your document</summary>${buttons(evidence)}</details>`;
    panel.querySelectorAll('[data-source]').forEach(b=>b.onclick=()=>CitationDrawer.open(b.dataset.source));
  }
}
