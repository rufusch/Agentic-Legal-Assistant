import { LegalApiClient, escapeHtml } from '../api/api-client.js';
import { ChatApi } from '../api/chat-api.js';
import { Icons } from '../components/icons.js';
import { CitationDrawer } from '../components/citation-drawer.js';

const esc = (s) => {
  if (!s) return '';
  return escapeHtml(s);
};

function formatMarkdown(text) {
  if (!text) return '';
  let s = esc(text);
  
  // Headers
  s = s.replace(/^### (.*$)/gim, '<h4 class="supplied-93bbe94c84">$1</h4>');
  s = s.replace(/^## (.*$)/gim, '<h3 class="supplied-8630bac63b">$1</h3>');
  
  // Blockquotes
  s = s.replace(/^>\s*(.*$)/gim, '<blockquote class="supplied-d7ca7ad1ea">$1</blockquote>');

  // Bold & Italic
  s = s.replace(/\*\*(.*?)\*\*/g, '<strong class="supplied-09264f018e">$1</strong>');
  s = s.replace(/\*(.*?)\*/g, '<em>$1</em>');
  
  // Inline Code
  s = s.replace(/`([^`]+)`/g, '<code class="supplied-93ac859443">$1</code>');
  
  // Bullet items
  s = s.replace(/^\s*[\-\*]\s+(.*$)/gim, '<div class="supplied-c056a55d38"><span class="supplied-22fbd884b1">•</span><span class="supplied-6253876a64">$1</span></div>');
  
  // Numbered items
  s = s.replace(/^\s*(\d+)\.\s+(.*$)/gim, '<div class="supplied-c056a55d38"><span class="supplied-0670488006">$1.</span><span class="supplied-6253876a64">$2</span></div>');
  
  // Paragraphs & Line breaks
  s = s.replace(/\n\n/g, '<div class="supplied-83d9340780"></div>');
  s = s.replace(/\n/g, '<br/>');
  return s;
}

export class ChatView {
  constructor(el, onNavigate) {
    this.el = el;
    this.onNavigate = onNavigate;
    this.state = 'setup';
    this.convoId = null;
    this.docs = [];
    this.selectedDocs = [];
    this.loaded = false;
    this.sub = null;
    this.messages = [];
  }

  async render() {
    if (!this.loaded) {
      const docs=(await LegalApiClient.listDocuments()).data.filter(d=>d.status==='ready');
      this.docs=docs.slice(0,30).map(d=>({id:d.id,name:d.name}));this.selectedDocs=this.docs.map(d=>d.id);this.loaded=true;
      this.model=(await ChatApi.config()).data.model;
      const saved=sessionStorage.getItem('caselens.chat.conversation:'+sessionStorage.getItem('caselens.tenant'));
      if(saved){try{const response=await ChatApi.getMessages(saved);this.convoId=saved;const last=response.data.filter(m=>m.role==='user').at(-1);if(last){this.selectedDocs=last.source_document_ids;this.docs=docs.filter(d=>this.selectedDocs.includes(d.id)).map(d=>({id:d.id,name:d.name}));}}catch(e){if(e.status!==404)throw e;}}
    }
    if (!this.convoId) {
      try {
        const cRes = await ChatApi.createConversation({ title: 'New Chat', document_ids: this.selectedDocs });
        this.convoId = cRes.data.conversation_id;
        sessionStorage.setItem('caselens.chat.conversation:'+sessionStorage.getItem('caselens.tenant'),this.convoId);
        this.state = 'chat';
      } catch (e) {
        window.showToast?.('Failed to create conversation', 'error');
        return;
      }
    }
    await this._renderChat();
  }

  _renderAttachedResources() {
    const listEl = this.el.querySelector('#attached-resources-list');
    const tagsEl = this.el.querySelector('#attached-tags-container');

    if (listEl) {
      if (this.docs.length === 0) {
        listEl.innerHTML = `<div class="supplied-9c8d605a75">No documents attached.</div>`;
      } else {
        listEl.innerHTML = this.docs.map(d => `
          <div class="card rv-card supplied-339185e6a2">
            <div class="supplied-8a25d40816">${Icons.fileText('', 16)}</div>
            <div title="${esc(d.name)}" class="supplied-4d95762306">${esc(d.name)}</div>
            <button class="remove-doc-btn btn btn-ghost btn-sm supplied-072ed14989" data-id="${d.id}" title="Remove document">&times;</button>
          </div>
        `).join('');
      }

      listEl.querySelectorAll('.remove-doc-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const docId = btn.getAttribute('data-id');
          this.docs = this.docs.filter(d => d.id !== docId);
          this.selectedDocs = this.selectedDocs.filter(id => id !== docId);
          this._renderAttachedResources();
        });
      });
    }

    if (tagsEl) {
      if (this.docs.length === 0) {
        tagsEl.innerHTML = '';
      } else {
        tagsEl.innerHTML = this.docs.map(d => `
          <span class="supplied-789e3f6ee4">
            ${Icons.fileText('', 12)} ${esc(d.name)}
            <span class="remove-tag-btn supplied-7eac577043" data-id="${d.id}">&times;</span>
          </span>
        `).join('');

        tagsEl.querySelectorAll('.remove-tag-btn').forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const docId = btn.getAttribute('data-id');
            this.docs = this.docs.filter(d => d.id !== docId);
            this.selectedDocs = this.selectedDocs.filter(id => id !== docId);
            this._renderAttachedResources();
          });
        });
      }
    }
  }

  _renderMsgFooter(m) {
    return `<div class="supplied-553670d73d">
      <button class="btn btn-ghost btn-sm chat-copy" data-message-id="${m.id}">Copy</button>
      <button class="btn btn-ghost btn-sm chat-helpful" data-message-id="${m.id}">Helpful</button>
      <span>Source support checked; human review required.</span>
      ${(m.citations||[]).map(c=>`<button class="btn btn-ghost btn-sm chat-citation" data-citation-id="${c.id}">[${esc(c.label)}] ${esc(c.document_name)}</button>`).join('')}
      ${(m.warnings||[]).map(w=>`<div>${esc(w.message)}</div>`).join('')}
    </div>`;
  }

  _appendMessageNode(m) {
    const isUser = m.role === 'user';
    const wrapper = document.createElement('div');
    wrapper.className = 'chat-message-item';
    wrapper.setAttribute('data-msg-id', m.id);

    if (isUser) {
      wrapper.style.cssText = 'display: flex; flex-direction: column; align-items: flex-end; padding: 0 2rem; margin-bottom: 1.5rem;';
      wrapper.innerHTML = `
        <div class="supplied-a4235dbe4d">
          <span>You</span>
          <div class="supplied-34f90158d3">
            ${Icons.user('', 12)}
          </div>
        </div>
        <div class="supplied-04f6e02712">
          ${esc(m.content)}
        </div>
      `;
    } else {
      wrapper.style.cssText = 'display: flex; flex-direction: column; align-items: flex-start; padding: 0 2rem; margin-bottom: 1.5rem; width: 100%;';
      wrapper.innerHTML = `
        <div class="supplied-d459d5fea6">
          <div class="supplied-f1dfe31e36">
            ${Icons.sparkles('', 13)}
          </div>
          <span>CaseLens AI</span>
        </div>
        
        <div class="supplied-393f90ef05">
          <div id="msg-body-${m.id}">
            ${m.status === 'queued' ? `
              <div class="supplied-30d88e4d8a">
                <div class="btn-spinner supplied-2ff863c6ee"></div>
                Thinking & retrieving legal context...
              </div>
            ` : formatMarkdown(m.content || m.failure?.message || (m.status==='cancelled'?'Answer cancelled.':'Retrieving and checking source evidence…'))}
          </div>

          <div id="msg-footer-${m.id}">
            ${['completed','completed_with_warnings'].includes(m.status) ? this._renderMsgFooter(m) : ''}
          </div>
        </div>
      `;
    }

    this.historyEl.appendChild(wrapper);
    this.historyEl.scrollTop = this.historyEl.scrollHeight;
  }

  async _renderChat() {
    this.sub?.close();this.sub=null;
    this.conversations=(await ChatApi.list()).data.items;
    this.el.innerHTML = `
      <input type="file" id="chat-file-input" multiple accept=".pdf,.docx,.doc,.txt,.png,.jpg" / class="supplied-6e22c58a7a">

      <div class="chat-shell supplied-8a4729ab88">
        
        <!-- Left Sidebar: Chat History -->
        <div class="chat-sidebar supplied-21266d4498">
          <button class="btn btn-ghost supplied-649b6e222e" id="new-chat-btn">
            ${Icons.plus('', 16)} <span class="supplied-db4dd366ec">New chat</span>
          </button>
          
          <div class="supplied-002dc26c47">
            <div class="supplied-4fa00029d5">
              <span class="supplied-c8d16c7f0c">${Icons.search('', 14)}</span>
              <input type="text" class="input supplied-10ec32351b" placeholder="Search chats" />
            </div>
          </div>
          
          <div class="supplied-b79da5ac72">
             <label class="supplied-37e4f886d5">Recents</label>
             
             ${this.conversations.map(c=>`<button class="card rv-card chat-recent ${c.id===this.convoId?'chat-recent-active':''}" data-conversation-id="${c.id}">${esc(c.title)}</button>`).join('')}

          </div>
        </div>

        <!-- Center: Main Chat Area -->
        <div class="chat-main supplied-beafea5b41">
          <!-- Main content area -->
          <div id="chat-history" class="supplied-77b3528da4">
            <div class="btn-spinner supplied-2afd3ac81e"></div>
          </div>

          <!-- Input bar (rounded block style) -->
          <div class="supplied-e35ec641ff">
            <div class="supplied-5fdf5cbcdc">
              
              <!-- Attached Tags Container -->
              <div id="attached-tags-container" class="supplied-b35783accd"></div>

              <div class="supplied-bfb533c7a8">
                <input type="text" id="chat-input" class="input supplied-4da4b1bf8c" placeholder="Ask CaseLens AI about your attached documents..." />
              </div>
              
              <div class="supplied-2c6b7ba3c1">
                <div class="supplied-de5f517180">
                  <button id="chat-upload-plus" title="Upload files" class="btn btn-ghost btn-sm supplied-c57f342301">
                    ${Icons.plus('', 16)}
                  </button>
                  <button id="chat-upload-doc" title="Attach document" class="btn btn-ghost btn-sm supplied-c57f342301">
                    ${Icons.fileText('', 16)}
                  </button>
                  <button id="chat-model-settings" title="Model settings" class="btn btn-ghost btn-sm supplied-f1f8cb9c6d">${Icons.settings('', 16)}</button>
                </div>
                <div class="supplied-c8cee58622">
                  <span class="supplied-eae82f968d">${esc(this.model?.version || "RAG Chat")}</span>
                  <button id="chat-stop" class="btn btn-ghost btn-sm" hidden>Stop</button>
                  <button class="btn btn-primary supplied-94d6cab373" id="chat-send">
                    ${Icons.arrowRight('', 16)}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Right Sidebar: Resources & Context -->
        <div class="chat-resources supplied-cc3690339c">
          <h3 class="supplied-5b259598f1">Resources</h3>
          
          <div class="supplied-6f33a5c09d">
             <label class="supplied-e9b63f21cd">Attached</label>
             
             <div id="attached-resources-list" class="supplied-5bd71d6712"></div>
             
             <button id="add-resource-btn" class="btn btn-ghost btn-sm supplied-1458f8aab7">
               ${Icons.plus('', 14)} <span class="supplied-541924b788">Add resource</span>
             </button>
          </div>
        </div>
      </div>
    `;

    this.el.querySelectorAll('.chat-recent').forEach(b=>b.onclick=async()=>{
      this.sub?.close();this.sub=null;this.convoId=b.dataset.conversationId;
      sessionStorage.setItem('caselens.chat.conversation:'+sessionStorage.getItem('caselens.tenant'),this.convoId);
      const response=await ChatApi.getMessages(this.convoId);const last=response.data.filter(m=>m.role==='user').at(-1);
      if(last){this.selectedDocs=last.source_document_ids;this.docs=(await LegalApiClient.listDocuments()).data.filter(d=>d.status==='ready'&&this.selectedDocs.includes(d.id)).map(d=>({id:d.id,name:d.name}));}
      await this._renderChat();
    });
    this.el.querySelector('[placeholder="Search chats"]').oninput=e=>this.el.querySelectorAll('.chat-recent').forEach(b=>b.hidden=!b.textContent.toLowerCase().includes(e.target.value.toLowerCase()));
    this.historyEl = this.el.querySelector('#chat-history');
    this._renderAttachedResources();
    await this._refreshMessages();

    const fileInput = this.el.querySelector('#chat-file-input');
    const uploadPlus = this.el.querySelector('#chat-upload-plus');
    const uploadDoc = this.el.querySelector('#chat-upload-doc');
    const addResource = this.el.querySelector('#add-resource-btn');

    const triggerUpload = () => fileInput.click();
    uploadPlus.addEventListener('click', triggerUpload);
    uploadDoc.addEventListener('click', triggerUpload);
    addResource.addEventListener('click', triggerUpload);

    fileInput.addEventListener('change', async e => {
      const files=Array.from(e.target.files); if(!files.length)return;
      const button=this.el.querySelector('#chat-send');button.disabled=true;
      try {for(const f of files){const d=(await LegalApiClient.uploadDocument(f,{document_type:'case',jurisdiction:'IN',title:f.name})).data;this.docs.push({id:d.id,name:d.name});this.selectedDocs.push(d.id);}this._renderAttachedResources();window.app.updateDocBadgeCount();window.showToast?.('Documents parsed and attached.','success');}
      catch(e){window.showToast?.(e.message,'error');}finally{button.disabled=false;fileInput.value='';}
    });
    this.el.onclick=async e=>{
      const copy=e.target.closest('.chat-copy');if(copy){const m=this.messages.find(m=>m.id===copy.dataset.messageId);await navigator.clipboard.writeText(m.content);window.showToast?.('Copied','success');}
      const helpful=e.target.closest('.chat-helpful');if(helpful){try{await ChatApi.feedback(this.convoId,helpful.dataset.messageId,{accepted:true,use_for_training:false});window.showToast?.('Feedback saved. Training permission remains off.','success');}catch(error){window.showToast?.(error.message,'error');}}
    };

    this.el.querySelector('#chat-model-settings').onclick=()=>window.showToast?.('Model: '+this.model.version+'. Sources are limited to attached documents; model credentials stay on the backend.');
    const sendBtn = this.el.querySelector('#chat-send');
    const input = this.el.querySelector('#chat-input');

    const sendMsg = async () => {
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      sendBtn.disabled = true;input.disabled=true;

      // Clear welcome screen if present
      const welcome = this.historyEl.querySelector('.chat-welcome');
      if (welcome) {
        this.historyEl.innerHTML = '';
        this.historyEl.style.alignItems = 'stretch';
        this.historyEl.style.justifyContent = 'flex-start';
      }

      try {
        const res = await ChatApi.sendMessage(this.convoId, { content: text, selected_document_ids: this.selectedDocs });
        const { user_message_id, assistant_message_id, job_id } = res.data;

        // Fetch fresh message state from API
        const msgsRes = await ChatApi.getMessages(this.convoId);
        this.messages = msgsRes.data;

        const userMsg = this.messages.find(m => m.id === user_message_id);
        const asstMsg = this.messages.find(m => m.id === assistant_message_id);

        if (userMsg) this._appendMessageNode(userMsg);
        if (asstMsg) this._appendMessageNode(asstMsg);

        this._followJob(job_id,sendBtn,input);

      } catch (e) {
        input.value=text;window.showToast?.(e.message || 'Failed to send message', 'error');
        sendBtn.disabled = false;input.disabled=false;
      }
    };

    this.el.querySelector('#chat-stop').onclick=async()=>{try{await LegalApiClient.cancelJob(this.activeJobId);}catch(e){window.showToast?.(e.message,'error');}};
    const pending=this.messages.find(m=>m.role==='assistant'&&!['completed','completed_with_warnings','failed','cancelled'].includes(m.status));
    if(pending)this._followJob(pending.job_id,sendBtn,input);
    const prompt=sessionStorage.getItem('caselens.chat.prompt');if(prompt){input.value=prompt;sessionStorage.removeItem('caselens.chat.prompt');}
    sendBtn.addEventListener('click', sendMsg);
    input.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && !sendBtn.disabled) sendMsg();
    });

    this.el.querySelector('#new-chat-btn').addEventListener('click', async () => {
      if(this.sub){window.showToast?.('Wait for the current answer before starting a new chat.');return;}
      this.convoId = null;
      this.messages = [];
      await this.render();
    });
  }

  _followJob(jobId,sendBtn,input) {
    sendBtn.disabled=true;input.disabled=true;this.activeJobId=jobId;this.el.querySelector('#chat-stop').hidden=false;
    this.sub?.close();
    this.sub=LegalApiClient.subscribeJobEvents(jobId,async evt=>{
      if(evt.event==='job.completed'||evt.event==='job.failed'||evt.data?.status==='cancelled'){
        this.sub?.close();this.sub=null;this.activeJobId=null;this.el.querySelector('#chat-stop').hidden=true;await this._refreshMessages();sendBtn.disabled=false;input.disabled=false;
        if(evt.event==='job.failed')window.showToast?.(evt.data.message,'error');
      }
    });
  }

  async _refreshMessages() {
    try {
      const res = await ChatApi.getMessages(this.convoId);
      this.messages = res.data;
      
      if (this.messages.length === 0) {
        this.historyEl.style.alignItems = 'center';
        this.historyEl.style.justifyContent = 'center';
        this.historyEl.innerHTML = `
          <div class="chat-welcome supplied-6455559b32">
            <div class="supplied-1b59d15d3e">
              ${esc(this.model?.version || "RAG Chat")} &nbsp; <span class="supplied-8a2daa0509">Legal Assistant</span>
            </div>
            
            <h1 class="supplied-63d84c40ec">How can I assist your legal work today?</h1>
            
            <div class="supplied-4acfee5667">
              <label class="supplied-05b7091065">Suggested Prompts</label>
              
              <div class="supplied-3cb304e21c">
                <div class="card rv-card quick-card supplied-6d2f721d3f" data-prompt="Analyze the attached master agreement and provide an executive summary with key risks.">
                   <div class="supplied-fa43b2ed20">${Icons.fileText('', 16)}</div>
                   <div>
                     <div class="supplied-ada5f73295">Analyze document</div>
                     <div class="supplied-85758413f0">Comprehensive summary and risk extraction for master agreements.</div>
                   </div>
                </div>
                
                <div class="card rv-card quick-card supplied-6d2f721d3f" data-prompt="Draft a standard mutual limitation of liability clause with a 12-month fee cap.">
                   <div class="supplied-fa43b2ed20">${Icons.edit('', 16)}</div>
                   <div>
                     <div class="supplied-ada5f73295">Draft a clause</div>
                     <div class="supplied-85758413f0">Draft enforceable liability, indemnity, or dispute resolution clauses.</div>
                   </div>
                </div>
                
                <div class="card rv-card quick-card supplied-6d2f721d3f" data-prompt="Research judicial precedents on Section 438 Cr.P.C. anticipatory bail duration.">
                   <div class="supplied-fa43b2ed20">${Icons.book('', 16)}</div>
                   <div>
                     <div class="supplied-ada5f73295">Research topic</div>
                     <div class="supplied-85758413f0">Synthesize binding Supreme Court and High Court precedents.</div>
                   </div>
                </div>
                
                <div class="card rv-card quick-card supplied-6d2f721d3f" data-prompt="Brainstorm 4 innovative litigation strategies for contract dispute arbitration.">
                   <div class="supplied-fa43b2ed20">${Icons.sparkles('', 16)}</div>
                   <div>
                     <div class="supplied-ada5f73295">Brainstorm strategies</div>
                     <div class="supplied-85758413f0">Generate strategic arbitration and negotiation avenues.</div>
                   </div>
                </div>
              </div>
            </div>
          </div>
        `;

        this.historyEl.querySelectorAll('.quick-card').forEach(card => {
          card.addEventListener('click', () => {
            const prompt = card.getAttribute('data-prompt');
            const input = this.el.querySelector('#chat-input');
            if (input) {
              input.value = prompt;
              this.el.querySelector('#chat-send')?.click();
            }
          });
        });
      } else {
        this.historyEl.style.alignItems = 'stretch';
        this.historyEl.style.justifyContent = 'flex-start';
        this.historyEl.innerHTML = '';
        this.messages.forEach(m => this._appendMessageNode(m));
      }
      this.historyEl.scrollTop = this.historyEl.scrollHeight;
    } catch (e) {
      console.error("Failed to refresh messages", e);
    }
  }
}
