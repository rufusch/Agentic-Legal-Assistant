import { LegalApiClient, request } from '../api/api-client.js';
import { ResearchApi } from '../api/research-api.js';
import { officialSourceLinks } from '../components/official-source-links.js';
import { renderCitationBadge } from '../components/shared-ui.js';
import { Icons } from '../components/icons.js';

const esc = (s) => {
  if (!s) return '';
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
};

export class ResearchView {
  constructor(el, onNavigate) {
    this.el = el;
    this.onNavigate = onNavigate;
    this.state = 'setup'; // 'setup', 'running', 'completed'
    this.form = { question: '', jurisdiction: '', document_ids: [] };
    this.docs = [];
    this.jobId = null;
    this.researchId = null;
    this.researchData = null;
    this.progressLogs = [];
  }

  async render() {
    if (this.state === 'setup') {
      await this._renderSetup();
    } else if (this.state === 'running') {
      this._renderRunning();
    } else if (this.state === 'completed') {
      this._renderCompleted();
    }
  }

  async _renderSetup() {
    this.el.innerHTML = `
      <div class="view-header">
        <div class="view-title-group">
          <div class="rv-eyebrow">Workflow 3 &middot; Legal Research</div>
          <h1>Legal Research Memo</h1>
          <p class="view-subtitle">Generate fully grounded research memos with verifiable citations.</p>
        </div>
      </div>
      <div class="rv-setup-grid">
        <section class="card rv-card">
          <h3 class="supplied-726cf47beb">1. Research Question</h3>
          <textarea id="res-question" class="textarea" rows="5" placeholder="e.g. Precedents on anticipatory bail under Section 438 in State X..."></textarea>
          
          <label class="rv-label supplied-9a7472a9ec">Jurisdiction / Court (Optional)</label>
          <input type="text" id="res-jurisdiction" class="input" placeholder="e.g. Supreme Court, Delhi High Court" />
        </section>

        <section class="card rv-card">
          <h3 class="supplied-726cf47beb">2. Context Documents (Optional)</h3>
          <p class="rv-help supplied-726cf47beb">Select case files or upload new ones.</p>
          <p class="rv-help">Relevant official documents are fetched from the source catalog during research. Coverage is limited; you can add a specific government or court PDF below.</p>
          <label class="rv-label">Official PDF or India Code page URL</label>
          <input id="official-url" class="input" type="url" placeholder="https://www.indiacode.nic.in/…" />
          <label class="rv-label">Source title</label>
          <input id="official-title" class="input" maxlength="200" placeholder="Act or case name" />
          <select id="official-kind" class="input"><option value="statute">Statute</option><option value="judgment">Judgment</option></select>
          <button id="official-import" type="button" class="btn btn-secondary">Fetch official source</button>
          <p id="official-status" role="status"></p>
          <div id="res-docs-list" class="supplied-791e8d4d21">
            <div class="btn-spinner"></div>
          </div>
          
          <div class="rv-upload-box supplied-b793e3bd27" id="res-upload-box">
            <input type="file" id="res-file-upload" multiple accept=".pdf,.doc,.docx,.txt" / class="supplied-6aa34d7432">
            <div class="supplied-452d29f3c3">${Icons.fileText('', 24)}</div>
            <div class="supplied-9ba466d5e8">Click or drag documents to upload</div>
            <div class="supplied-8d444aeb9d">PDF, DOCX, TXT · legacy DOC depends on server parser</div>
            <div id="res-upload-status" class="supplied-a90aae6521"></div>
          </div>
        </section>
      </div>
      <div class="rv-actions supplied-8b6b19cac2">
        <div></div>
        <button class="btn btn-primary" id="res-submit">${Icons.search('', 15)} <span>Run Research</span></button>
      </div>
    `;

    this.el.querySelector('#official-import').onclick=async()=>{
      const button=this.el.querySelector('#official-import'),status=this.el.querySelector('#official-status');button.disabled=true;
      try{
        const result=await request('official-sources/import',{method:'POST',body:{url:this.el.querySelector('#official-url').value.trim(),title:this.el.querySelector('#official-title').value.trim(),document_type:this.el.querySelector('#official-kind').value}});
        status.textContent='Official source imported. It is available for research, drafting and chat.';
        const doc=await LegalApiClient.getDocument(result.data.document_id);
        this.docs.push(doc.data);this.form.document_ids.push(doc.data.id);
        const label=document.createElement('label'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.value=result.data.document_id;checkbox.className='doc-cb';checkbox.checked=true;
        label.append(checkbox,document.createTextNode(doc.data.name));this.el.querySelector('#res-docs-list').append(label);
      }catch(e){status.textContent=e.message;}finally{button.disabled=false;}
    };
    try {
      const res = await LegalApiClient.listDocuments({ status: 'ready' });
      this.docs = res.data;
      this.form.document_ids=this.form.document_ids.filter(id=>this.docs.some(d=>d.id===id));
      const listEl = this.el.querySelector('#res-docs-list');
      if (this.docs.length === 0) {
        listEl.innerHTML = '<div class="rv-empty">No documents found.</div>';
      } else {
        listEl.innerHTML = this.docs.map(d => `
          <label class="supplied-3f288d39e2">
            <input type="checkbox" value="${d.id}" class="doc-cb" />
            <span class="supplied-7ba9bad628">${esc(d.name)}</span>
          </label>
        `).join('');
      }
    } catch (e) {
      console.error(e);
    }

    this.el.querySelector('#res-question').value=this.form.question;
    this.el.querySelector('#res-jurisdiction').value=this.form.jurisdiction;

    // Upload functionality
    const uploadBox = this.el.querySelector('#res-upload-box');
    const fileInput = this.el.querySelector('#res-file-upload');
    const statusDiv = this.el.querySelector('#res-upload-status');

    const handleFiles = async (files) => {
      if (files.length === 0) return;
      statusDiv.textContent = `Uploading ${files.length} file(s)...`;
      const button=this.el.querySelector('#res-submit');button.disabled=true;
      try {
        for(const file of files) await LegalApiClient.uploadDocument(file,{title:file.name,document_type:'case',jurisdiction:'IN'});
        window.showToast?.('Documents parsed and ready. Select them as context.','success');
        this.form.question=this.el.querySelector('#res-question').value;
        this.form.jurisdiction=this.el.querySelector('#res-jurisdiction').value;
        await this._renderSetup();
      } catch(e){statusDiv.textContent=e.message;window.showToast?.(e.message,'error');}
      finally{button.disabled=false;}

    };

    uploadBox.addEventListener('click', e => { if(e.target!==fileInput) fileInput.click(); });
    fileInput.addEventListener('change', (e) => handleFiles(e.target.files));
    uploadBox.addEventListener('dragover', (e) => {
      e.preventDefault();
      uploadBox.style.borderColor = 'var(--brand-primary)';
      uploadBox.style.background = 'rgba(122, 28, 43, 0.05)';
    });
    uploadBox.addEventListener('dragleave', (e) => {
      e.preventDefault();
      uploadBox.style.borderColor = 'var(--border)';
      uploadBox.style.background = 'transparent';
    });
    uploadBox.addEventListener('drop', (e) => {
      e.preventDefault();
      uploadBox.style.borderColor = 'var(--border)';
      uploadBox.style.background = 'transparent';
      handleFiles(e.dataTransfer.files);
    });

    this.el.querySelector('#res-submit').addEventListener('click', async () => {
      const button=this.el.querySelector('#res-submit');
      if(button.disabled)return;
      const q = this.el.querySelector('#res-question').value.trim();
      if (!q) {
        window.showToast?.('Research question is required.', 'error');
        return;
      }
      this.form.question = q;
      this.form.jurisdiction = this.el.querySelector('#res-jurisdiction').value.trim();
      this.form.document_ids = Array.from(this.el.querySelectorAll('.doc-cb:checked')).map(cb => cb.value);

      button.disabled=true;
      try {
        const createRes = await ResearchApi.createResearch(this.form);
        this.researchId = createRes.data.research_id;
        this.jobId = createRes.data.job_id;
        this.state = 'running';
        this.render();
        this._subscribeToJob();
      } catch (e) {
        window.showToast?.(e.message || 'Failed to start research.', 'error');
        button.disabled=false;
      }
    });
    this.el.querySelector('#res-question').oninput=e=>{this.form.question=e.target.value;};
    this.el.querySelector('#res-jurisdiction').oninput=e=>{this.form.jurisdiction=e.target.value;};
    this.el.querySelector('#res-docs-list').onchange=()=>{this.form.document_ids=[...this.el.querySelectorAll('.doc-cb:checked')].map(cb=>cb.value);};
    this.el.querySelectorAll('.doc-cb').forEach(cb=>{cb.checked=this.form.document_ids.includes(cb.value);});
    const history=await ResearchApi.list().then(res=>res.data.items).catch(error=>{window.showToast?.(error.message || 'Could not load previous research','error');return [];});
    const historyCard=document.createElement('section');historyCard.className='card';historyCard.style.marginTop='1rem';const heading=document.createElement('h3');heading.textContent='Previous research';historyCard.append(heading);
    for(const memo of history){const b=document.createElement('button');b.className='btn btn-secondary';b.style.margin='0.5rem';b.textContent=memo.question+' · '+memo.status;b.onclick=async()=>{this.researchId=memo.id;this.jobId=memo.job_id;if(['completed','completed_with_warnings'].includes(memo.status)){this.researchData=(await ResearchApi.getResearch(memo.id)).data;this.state='completed';this.render();}else if(['failed','cancelled'].includes(memo.status)){window.showToast?.(memo.failure?.message||memo.status,'error');}else{this.state='running';this.render();this._subscribeToJob();}};historyCard.append(b);}this.el.append(historyCard);

  }

  _renderRunning() {
    this.el.innerHTML = `
      <div class="view-header">
        <div class="view-title-group">
          <div class="rv-eyebrow">Legal Research</div>
          <h1>Compiling Memo...</h1>
        </div>
      </div>
      <div class="card rv-card supplied-1dda61780b">
        <h3 class="supplied-d6951963d2"><div class="btn-spinner"></div> Pipeline Status</h3>
        <ul id="res-logs" class="rv-log supplied-002dc26c47">
          ${this.progressLogs.map(l => `<li><span class="rv-log-time">${new Date().toLocaleTimeString()}</span> <span>${esc(l.message)}</span></li>`).join('')}
        </ul>
        <button class="btn btn-ghost" id="res-cancel">Cancel Job</button>
      </div>
    `;
    this.el.querySelector('#res-cancel').addEventListener('click', async () => {
      try {await LegalApiClient.cancelJob(this.jobId);this.sub?.close();} catch(e){window.showToast?.(e.message,'error');return;}
      window.showToast?.('Research cancelled.');
      this.state = 'setup';
      this.render();
    });
  }

  _subscribeToJob() {
    const sub = this.sub = LegalApiClient.subscribeJobEvents(this.jobId, async (evt) => {
      if(evt.event==='job.failed'||evt.data?.status==='cancelled'){sub.close();this.state='setup';window.showToast?.(evt.data.message||'Research cancelled','error');await this.render();return;}
      if (evt.event === 'job.progress') {
        this.progressLogs.push(evt.data);
        if (this.state === 'running') { const list=this.el.querySelector('#res-logs'); if(list){const li=document.createElement('li');li.textContent=evt.data.message || evt.data.status;list.append(li);} }
      } else if (evt.event === 'job.completed') {
        sub.close();
        try {
          const res = await ResearchApi.getResearch(this.researchId);
          this.researchData = res.data;
          this.state = 'completed';
          this.render();
        } catch (e) {
          window.showToast?.(e.message || 'Failed to fetch results.', 'error');
          this.state='setup';await this.render();
        }
      }
    });
  }

  _renderCompleted() {
    const d=this.researchData;
    const cites=ids=>(ids||[]).map(id=>renderCitationBadge(d.citations.find(c=>c.id===id)?.label||'Source',id)).join('');
    this.el.innerHTML=`<div class="view-header"><div class="view-title-group"><div class="rv-eyebrow">Legal Research</div><h1>Research Memo</h1><p class="view-subtitle">${esc(d.question)}</p></div><div><button class="btn btn-secondary" id="res-export">Export PDF</button><button class="btn btn-primary" id="res-new">New Search</button></div></div>
      ${officialSourceLinks(d.citations)}
      <div class="rv-setup-grid"><section class="card rv-card"><h3>Executive summary</h3><p>${esc(d.executive_summary.text)}</p>${cites(d.executive_summary.citation_ids)}
      ${d.legal_framework.map(s=>`<article class="supplied-80dfcf9181"><h3>${esc(s.heading)}</h3><p>${esc(s.analysis)}</p>${cites(s.citation_ids)}</article>`).join('')}
      ${d.application_to_facts.map(s=>`<article class="supplied-80dfcf9181"><h3>Application to facts</h3><p>${esc(s.analysis)}</p><p>Fact sources: ${cites(s.fact_citation_ids)}</p><p>Authority sources: ${cites(s.law_citation_ids)}</p></article>`).join('')}
      <h3 class="supplied-80dfcf9181">Limitations</h3>${d.limitations.map(v=>`<p class="warning-box warning">${esc(v)}</p>`).join('')}</section>
      <aside><section class="card rv-card"><h3>Confidence</h3><p>${esc(d.confidence.level)} · ${Math.round(d.confidence.score*100)}%</p><p>${esc(d.confidence.explanation)}</p></section><section class="card rv-card supplied-66e6b652a6"><h3>Research coverage</h3>${d.sub_queries.map(q=>`<p class="supplied-992b7d83bd">${esc(q.question)}<br><strong>${esc(q.status)}</strong></p>`).join('')}<p>Working memo · human legal review required.</p></section></aside></div>`;
    this.el.querySelector('#res-new').onclick=()=>{this.state='setup';this.progressLogs=[];this.render();};
    this.el.querySelector('#res-export').onclick=async()=>{try{await ResearchApi.exportResearch(this.researchId,'pdf');}catch(e){window.showToast?.(e.message,'error');}};
  }
}
