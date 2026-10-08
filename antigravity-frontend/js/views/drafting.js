/* ==========================================================================
   WORKFLOW 2 — LEGAL DRAFTING VIEW (Contract Section 4)
   States: setup -> checking_requirements -> awaiting_information -> 
           ready_to_draft -> drafting -> verifying -> completed
   ========================================================================== */

import { LegalApiClient } from '../api/api-client.js';
import { DraftingApi } from '../api/drafting-api.js';
import { renderCitationBadge, renderWarningBox, renderPipelineTracker } from '../components/shared-ui.js';
import { Icons } from '../components/icons.js';

const DRAFTING_DRAFT_KEY = 'caselens.drafting.draft';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const JURISDICTIONS = [
  ['IN', 'India (Federal)'], ['IN-MH', 'India — Maharashtra'], ['IN-DL', 'India — Delhi']
];

const DOC_TYPES = [
  ['anticipatory_bail_application', 'Anticipatory Bail Application'],
  ['affidavit','Affidavit'], ['contract_clause','Contract clause'],
  ['notice', 'Legal Notice'],
  ['petition', 'Writ Petition']
];

export class DraftingView {
  constructor(containerEl, onNavigate) {
    this.el = containerEl;
    this.onNavigate = onNavigate;
    this.state = 'setup';
    this.form = this._loadDraft();
    this.fieldErrors = {};
    this.docs = [];
    
    // Live draft state
    this.draftId = null;
    this.jobId = null;
    this.draftData = null;
    this.requirements = [];
    this.sub = null;
    this.lastEventId = 0;
    this.log = [];
  }

  /* ------------------------------------------------------------------ */
  async render() {
    if (this.state === 'setup') return this._renderSetup();
    if (this.state === 'awaiting_information' || this.state === 'ready_to_draft') return this._renderRequirements();
    if (this.state === 'drafting' || this.state === 'verifying') return this._renderRunning();
    if (this.state === 'completed') return this._renderEditor();
    
    // Default fallback
    return this._renderRunning();
  }

  _defaultForm() {
    return {
      document_type: 'anticipatory_bail_application',
      jurisdiction: 'IN-MH',
      court: 'High Court of Bombay',
      instructions: '',
      supporting_document_ids: []
    };
  }
  _loadDraft() {
    try {
      const d = JSON.parse(localStorage.getItem(DRAFTING_DRAFT_KEY+':'+sessionStorage.getItem('caselens.tenant')));
      if (d && d.document_type) return d;
    } catch { /* ignore corrupt draft */ }
    return this._defaultForm();
  }
  _saveDraft() { localStorage.setItem(DRAFTING_DRAFT_KEY+':'+sessionStorage.getItem('caselens.tenant'), JSON.stringify(this.form)); }

  _fieldError(name) {
    return this.fieldErrors[name] ? `<div class="rv-field-error" role="alert">${esc(this.fieldErrors[name])}</div>` : '';
  }

  /* =========================== SETUP ================================= */
  async _renderSetup() {
    const res = await LegalApiClient.listDocuments();
    this.docs = res.data;
    const ready=new Set(this.docs.filter(d=>d.status==='ready').map(d=>d.id));
    this.form.supporting_document_ids=this.form.supporting_document_ids.filter(id=>ready.has(id));
    const readyDocs = this.docs.filter(d => d.status === 'ready');
    
    this.el.innerHTML = `
      <div class="view-header">
        <div class="view-title-group">
          <div class="rv-eyebrow">Workflow 2 &middot; Legal Drafting Engine</div>
          <h1>New Draft</h1>
          <p class="view-subtitle">Select the document type and provide instructions. CaseLens will determine missing information and build a verifiable draft.</p>
        </div>
      </div>

      <div class="rv-setup-grid">
        <section class="card rv-card">
          <h3 style="margin-bottom: 1rem;">1. Document Details</h3>
          
          <div class="rv-row2">
            <div>
              <label class="rv-label" for="df-type">Document Type</label>
              <select id="df-type" class="select">
                ${DOC_TYPES.map(([v, l]) => `<option value="${v}" ${this.form.document_type === v ? 'selected' : ''}>${l}</option>`).join('')}
              </select>
              ${this._fieldError('document_type')}
            </div>
            <div>
              <label class="rv-label" for="df-jur">Jurisdiction</label>
              <select id="df-jur" class="select">
                ${JURISDICTIONS.map(([v, l]) => `<option value="${v}" ${this.form.jurisdiction === v ? 'selected' : ''}>${l} (${v})</option>`).join('')}
              </select>
            </div>
          </div>

          <label class="rv-label" for="df-court" style="margin-top: 1rem;">Court / Authority</label>
          <input type="text" id="df-court" class="input" value="${esc(this.form.court)}" placeholder="e.g. High Court of Bombay">

          <label class="rv-label" for="df-inst" style="margin-top: 1rem;">Instructions & Context</label>
          <textarea class="textarea" id="df-inst" rows="4" placeholder="Briefly explain what needs to be drafted...">${esc(this.form.instructions)}</textarea>
          ${this._fieldError('instructions')}
        </section>

        <section class="card rv-card">
          <h3 style="margin-bottom: 1rem;">2. Supporting Documents (Optional)</h3>
          <p class="rv-help">Select uploaded files to provide context or evidence for this draft.</p>
          <div class="rv-doc-list" id="df-doc-list">
            ${readyDocs.length === 0 ? '<div class="rv-empty">No ready documents.</div>' : readyDocs.map(d => {
              const checked = this.form.supporting_document_ids.includes(d.id);
              return `
              <label class="rv-doc-row ${checked ? 'selected' : ''}">
                <input type="checkbox" class="df-doc-check" value="${d.id}" ${checked ? 'checked' : ''} />
                <span class="rv-doc-icon">${Icons.fileText('', 16)}</span>
                <span class="rv-doc-main"><span class="rv-doc-name">${esc(d.name)}</span></span>
              </label>`;
            }).join('')}
          </div>
        </section>
      </div>

      <div class="rv-actions">
        <button class="btn btn-primary" id="df-submit"><span>Analyze Requirements</span>${Icons.arrowRight('', 15)}</button>
      </div>
    `;
    this._bindSetup();
    const history=(await DraftingApi.list()).data.items;
    const card=document.createElement('section');card.className='card';card.style.marginTop='1.5rem';
    const title=document.createElement('h3');title.textContent='Previous drafts';card.append(title);
    for(const d of history){const b=document.createElement('button');b.className='btn btn-secondary';b.style.margin='0.5rem';b.textContent=d.title+' · '+d.status;b.onclick=async()=>{this.draftId=d.id;this.jobId=d.job_id;if(['awaiting_information','ready_to_draft'].includes(d.status))await this._loadRequirements();else if(['completed','completed_with_warnings'].includes(d.status))await this._loadDraftData();else{this.state=d.status;this._renderRunning();this.sub?.close();this.sub=LegalApiClient.subscribeJobEvents(d.job_id,async evt=>{if(this._jobFailed(evt))return;if(evt.event==='job.completed'){this.sub.close();const job=(await LegalApiClient.getJob(d.job_id)).data;if(job.phase==='requirements')await this._loadRequirements();else await this._loadDraftData();}});}};card.append(b);}this.el.append(card);
  }

  _bindSetup() {
    const $ = (s) => this.el.querySelector(s);
    
    $('#df-type').addEventListener('change', (e) => { this.form.document_type = e.target.value; this._saveDraft(); });
    $('#df-jur').addEventListener('change', (e) => { this.form.jurisdiction = e.target.value; this._saveDraft(); });
    $('#df-court').addEventListener('change', (e) => { this.form.court = e.target.value; this._saveDraft(); });
    $('#df-inst').addEventListener('change', (e) => { this.form.instructions = e.target.value; this._saveDraft(); });

    $('#df-doc-list')?.addEventListener('change', (e) => {
      if (!e.target.classList.contains('df-doc-check')) return;
      const id = e.target.value;
      if (e.target.checked) this.form.supporting_document_ids.push(id);
      else this.form.supporting_document_ids = this.form.supporting_document_ids.filter(x => x !== id);
      e.target.closest('label').classList.toggle('selected', e.target.checked);
      this._saveDraft();
    });

    $('#df-submit').addEventListener('click', async () => {
      this.form={...this.form,document_type:$('#df-type').value,jurisdiction:$('#df-jur').value,court:$('#df-court').value,instructions:$('#df-inst').value,supporting_document_ids:[...this.el.querySelectorAll('.df-doc-check:checked')].map(i=>i.value)};
      this._saveDraft();
      this.fieldErrors = {};
      if (!this.form.instructions.trim()) this.fieldErrors.instructions = "Instructions are required.";
      
      if (Object.keys(this.fieldErrors).length) return this._renderSetup();

      const btn = $('#df-submit');
      btn.disabled = true;
      btn.innerHTML = '<span class="btn-spinner"></span><span>Analyzing</span>';

      try {
        const payload = { ...this.form };
        const res = await DraftingApi.createDraft(payload);
        this.draftId = res.data.draft_id;
        this.jobId = res.data.job_id;
        
        // Setup SSE listener for the setup job
        this.sub = LegalApiClient.subscribeJobEvents(this.jobId, (evt) => {
          if(this._jobFailed(evt)) return;
          if (evt.event === 'job.completed') {
            this.sub.close();
            this._loadRequirements();
          }
        });

        this.state = 'checking_requirements';
        this._renderRunning();
      } catch (err) {
        window.showToast?.('Error starting draft', 'error');
        this._renderSetup();
      }
    });
  }

  _jobFailed(evt) {
    if(evt.event==='job.failed'||evt.data?.status==='cancelled') {
      this.sub?.close(); this.state='setup';
      window.showToast?.(evt.data.message||'Drafting task cancelled.','error'); this._renderSetup(); return true;
    }
    return false;
  }

  /* ===================== REQUIREMENTS FORM =========================== */
  async _loadRequirements() {
    try {
      const res = await DraftingApi.getRequirements(this.draftId);
      this.requirements = res.data;
      this._evaluateReadiness();
      this._renderRequirements();
    } catch (e) {
      window.showToast?.('Could not load requirements', 'error');
    }
  }

  _evaluateReadiness() {
    const allRequiredMet = this.requirements.every(r => !r.required || r.current_answer);
    this.state = allRequiredMet ? 'ready_to_draft' : 'awaiting_information';
  }

  _renderRequirements() {
    const missingBlocking = this.requirements.filter(r => r.required && !r.current_answer).length;
    
    this.el.innerHTML = `
      <div class="view-header">
        <div class="view-title-group">
          <div class="rv-eyebrow">Workflow 2 &middot; Requirements</div>
          <h1>Missing Information</h1>
          <p class="view-subtitle">CaseLens requires the following information to prepare a complete draft. Missing non-blocking fields will be marked as placeholders.</p>
        </div>
      </div>
      
      <div class="card" style="max-width: 800px; margin: 0 auto;">
        ${this.requirements.map(req => `
          <div class="req-item" style="margin-bottom: 1.5rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--border);">
            <div style="display:flex; justify-content: space-between;">
              <label class="rv-label">${esc(req.question)} ${req.required ? '<span style="color:var(--danger)">*</span>' : ''}</label>
              <span class="badge ${req.source === 'template' ? 'badge-ready' : 'badge-processing'}">${esc(req.source)}</span>
            </div>
            <p class="rv-help">${esc(req.rationale)}</p>
            <input type="text" class="input req-input" data-req-id="${req.id}" value="${esc(req.current_answer || '')}" placeholder="Enter answer..." />
          </div>
        `).join('')}

        <div style="margin-top: 2rem; display: flex; justify-content: space-between; align-items: center;">
          <div style="color: ${missingBlocking > 0 ? 'var(--danger)' : 'var(--success)'}; font-weight: 500;">
            ${missingBlocking > 0 ? `${missingBlocking} required field(s) missing` : 'All required fields answered'}
          </div>
          <label style="margin-right:1rem"><input type="checkbox" id="df-ack"> Proceed with unanswered optional fields as visible placeholders</label><button class="btn btn-primary" id="df-generate" ${missingBlocking > 0 ? 'disabled' : ''}><span>Generate Draft</span>${Icons.arrowRight('', 15)}</button>
        </div>
      </div>
    `;

    this.el.querySelectorAll('.req-input').forEach(input => {
      input.addEventListener('input', (e) => {
        const id = e.target.getAttribute('data-req-id');
        const req = this.requirements.find(r => r.id === id);
        if (req) {
          req.current_answer = e.target.value.trim() || null;
          this._evaluateReadiness();
          const btn = this.el.querySelector('#df-generate');
          const missing = this.requirements.filter(r => r.required && !r.current_answer).length;
          btn.disabled = missing > 0;
          this.el.querySelector('div[style*="font-weight: 500"]').innerHTML = missing > 0 
            ? `<span style="color:var(--danger)">${missing} required field(s) missing</span>`
            : `<span style="color:var(--success)">All required fields answered</span>`;
        }
      });
    });

    this.el.querySelector('#df-generate').addEventListener('click', async () => {
      // Save requirements to backend
      const answers = this.requirements.filter(r => r.current_answer).map(r => ({ requirement_id: r.id, value: r.current_answer }));
      const missing=this.requirements.filter(r=>!String(r.current_answer??'').trim());
      if(missing.some(r=>r.required)) return window.showToast?.('Fill required fields.','error');
      if(missing.length&&!this.el.querySelector('#df-ack').checked) return window.showToast?.('Answer the optional gaps or explicitly acknowledge the placeholders.','error');
      try {
        await DraftingApi.updateRequirements(this.draftId, { answers: this.requirements.map(r=>({requirement_id:r.id,value:String(r.current_answer??'')})) });
        const res = await DraftingApi.generateDraft(this.draftId, { proceed_with_missing_information: missing.length>0, acknowledged_requirement_ids:missing.map(r=>r.id) });
        this.jobId = res.data.job_id;
        
        this.log = [{ t: new Date(), msg: 'Generation queued' }];
        this.state = 'drafting';
        this._renderRunning();

        this.sub?.close();
        this.sub = LegalApiClient.subscribeJobEvents(this.jobId, (evt) => {
          if(this._jobFailed(evt)) return;
          if (evt.event === 'job.progress') {
            this.state = evt.data.status;
            this.log.push({ t: new Date(), msg: evt.data.message });
            this._renderRunning();
          } else if (evt.event === 'job.completed') {
            this.sub.close();
            this._loadDraftData();
          }
        });
      } catch (err) {
        window.showToast?.('Failed to start generation', 'error');
      }
    });
  }

  /* ===================== RUNNING / WAITING =========================== */
  _renderRunning() {
    this.el.innerHTML = `
      <div class="view-header">
        <div class="view-title-group">
          <div class="rv-eyebrow">Workflow 2 &middot; Legal Drafting Engine</div>
          <h1>${this.state === 'checking_requirements' ? 'Analyzing Requirements' : 'Drafting Document'}</h1>
          <p class="view-subtitle">CaseLens is processing the request.</p>
        </div>
      </div>
      <div class="card">
         <div style="display:flex; justify-content:center; padding: 2rem;">
            <div class="btn-spinner" style="border-width:3px; width:30px; height:30px; border-top-color:var(--brand-primary);"></div>
         </div>
         <div style="text-align:center; color:var(--text-secondary);">${this.log.length > 0 ? esc(this.log[this.log.length-1].msg) : 'Loading...'}</div>
      </div>
    `;
    const cancel=document.createElement('button');cancel.className='btn btn-secondary';cancel.textContent='Cancel task';cancel.onclick=async()=>{try{await LegalApiClient.cancelJob(this.jobId);}catch(e){window.showToast?.(e.message,'error');}};this.el.append(cancel);
  }

  /* ===================== EDITOR =========================== */
  async _loadDraftData(version) {
    try {
      const [res, vRes] = await Promise.all([
        DraftingApi.getDraft(this.draftId, version),
        DraftingApi.getVersions(this.draftId)
      ]);
      this.draftData = res.data;
      this.versions = vRes.data;
      this.state = 'completed';
      this._renderEditor();
    } catch (e) {
      console.error('Draft load failed',e);window.showToast?.(e.message||'Could not load draft', 'error');
    }
  }

  _renderEditor() {
    const d = this.draftData;
    const hasUnverified = Boolean(d.needs_verification);
    const completedVersions = this.versions || [];

    // Format text: bold placeholders like [CASE NUMBER]
    const formatText = (text) => esc(text).replace(/(\[[A-Z\s]+\])/g, '<strong class="df-placeholder">$1</strong>');

    this.el.innerHTML = `
      <div class="view-header">
        <div class="view-title-group">
          <div class="rv-eyebrow">Workflow 2 &middot; Legal Drafting Engine</div>
          <h1>${esc(d.title)}</h1>
          <p class="view-subtitle">Version ${d.version} &middot; Working draft · human legal review required.</p>
        </div>
        <div class="rv-report-actions">
          <label class="rv-version-select">
            <span>Version</span>
            <select class="select" id="df-version">
              ${completedVersions.map(v => `<option value="${v.version}" ${v.version === d.version ? 'selected' : ''}>v${v.version}</option>`).join('')}
            </select>
          </label>
          <button class="btn btn-secondary" id="df-verify" ${!hasUnverified ? 'disabled' : ''}>${Icons.checkCircle('', 15)}<span>Verify Edits</span></button>
          <div class="rv-export">
            <button class="btn btn-secondary" id="df-export-toggle" aria-haspopup="menu" aria-expanded="false">
              ${hasUnverified ? '<span style="color:var(--danger)">⚠️</span>' : ''} ${Icons.download('', 15)}<span>Export</span>
            </button>
            <div class="rv-export-menu" id="df-export-menu" role="menu" hidden>
              <button role="menuitem" data-export="pdf">PDF (print)</button>
              <button role="menuitem" data-export="docx">Word document</button>
              <button role="menuitem" data-export="txt">Plain text</button>
            </div>
          </div>
          <button class="btn btn-primary" id="df-new">${Icons.plus('', 15)}<span>New Draft</span></button>
        </div>
      </div>
      
      ${d.warnings.map(w=>renderWarningBox(w)).join('')}
      ${hasUnverified ? `
        <div class="warning-box warning" style="margin-bottom: 1.5rem;">
          <div class="warning-icon">${Icons.alertTriangle('', 18)}</div>
          <div>
            <div class="warning-title">Unverified Edits</div>
            <div class="warning-message">You have made edits to the draft that have not been verified. Click "Verify Edits" to check your changes against the case facts and laws.</div>
          </div>
        </div>
      ` : ''}

      <div class="rv-setup-grid">
         <div class="card" style="flex: 2; padding: 3rem;">
            ${d.sections.map(sec => `
              <div class="df-section" style="margin-bottom: 2rem;" data-sec-id="${sec.id}">
                ${sec.heading ? `<h3 style="text-align:center; margin-bottom:1rem; text-transform:uppercase;">${esc(sec.heading)}</h3>` : ''}
                ${sec.blocks.map(b => `
                  <div style="position:relative; margin-bottom: 1rem;">
                    <p class="df-block" ${b.editable ? 'contenteditable="true"' : ''} data-block-id="${b.id}" style="line-height: 1.8; min-height: 1.8em; padding: 0.5rem; ${b.editable ? 'border: 1px dashed transparent; outline: none;' : ''}" onfocus="this.style.border='1px dashed var(--border)'" onblur="this.style.border='1px dashed transparent'">
                      ${formatText(b.text)}
                    </p><div>${(b.citation_ids||[]).map(id=>renderCitationBadge(d.citations.find(c=>c.id===id)?.label||'Source',id)).join('')}</div>
                    ${b.claim_ids.length > 0 ? `<div style="position:absolute; right: -2rem; top: 0.5rem;" title="Verified Sources">${Icons.checkCircle('var(--success)', 14)}</div>` : ''}
                  </div>
                `).join('')}
              </div>
            `).join('')}
         </div>
         <div style="flex: 1;">
            <div class="card">
               <h3 style="margin-bottom: 1rem;">Verification</h3>
               <p class="rv-help">Source quotes were checked. Model interpretation and legal correctness require human review.</p>
               <div style="padding: 1rem; background: var(--bg); border: 1px solid var(--border); border-radius: 4px; text-align:center; margin-bottom: 1.5rem;">
                  <div style="font-size: 1.5rem; font-weight: 600; color: ${hasUnverified ? 'var(--warning)' : 'var(--brand-primary)'};">${hasUnverified ? 'Pending' : Math.round(d.confidence.score * 100) + '%'}</div>
                  <div style="font-size: 0.85rem; color: var(--text-secondary); text-transform: uppercase;">Confidence</div>
               </div>
               
               ${d.unresolved_placeholders.length > 0 ? `
                  <div class="warning-box warning" style="margin-top: 1rem;">
                    <div class="warning-icon">${Icons.alertTriangle('', 18)}</div>
                    <div>
                      <div class="warning-title">Missing Requirements</div>
                      <div class="warning-message">This draft contains ${d.unresolved_placeholders.length} placeholders: <br/> ${d.unresolved_placeholders.map(p => `<strong class="df-placeholder">${esc(p.token)}</strong>`).join('<br/>')}</div>
                    </div>
                  </div>
               ` : ''}
            </div>
         </div>
      </div>
    `;
    this._bindEditor();
  }

  _bindEditor() {
    const $ = (s) => this.el.querySelector(s);
    
    // Editor blocks
    this.el.querySelectorAll('.df-block[contenteditable="true"]').forEach(block => {
      block.addEventListener('blur', async (e) => {
        const section=e.target.closest('.df-section');
        const text=[...section.querySelectorAll('.df-block')].map(b=>b.innerText.trim()).join('\n\n');
        const old=this.draftData.sections.find(s=>s.id===section.dataset.secId).blocks.map(b=>b.text.trim()).join('\n\n');
        if(text===old)return;
        const secId = e.target.closest('.df-section').getAttribute('data-sec-id');
        try {
          await DraftingApi.patchSection(this.draftId, secId, { text,base_version:this.draftData.version });
          this._loadDraftData(); // Reload to reflect unverified state
        } catch(err) {
          window.showToast?.('Failed to save edit', 'error');
        }
      });
    });

    // Version select
    $('#df-version')?.addEventListener('change', async (e) => {
      this._loadDraftData(Number(e.target.value));
    });

    // Verify
    $('#df-verify')?.addEventListener('click', async (e) => {
      e.currentTarget.disabled = true;
      e.currentTarget.innerHTML = '<span class="btn-spinner"></span><span>Verifying</span>';
      try {
        const res = await DraftingApi.verifyDraft(this.draftId);
        this.jobId = res.data.job_id;
        this.log = [{ t: new Date(), msg: 'Verification queued' }];
        this.state = 'verifying';
        this._renderRunning();
        
        this.sub?.close();
        this.sub = LegalApiClient.subscribeJobEvents(this.jobId, (evt) => {
          if(this._jobFailed(evt)) return;
          if (evt.event === 'job.progress') {
             this.log.push({ t: new Date(), msg: evt.data.message });
             this._renderRunning();
          } else if (evt.event === 'job.completed') {
             this.sub.close();
             this._loadDraftData();
          }
        });
      } catch (err) {
        window.showToast?.('Verification failed', 'error');
        this._renderEditor();
      }
    });

    // Export
    const toggle = $('#df-export-toggle');
    const menu = $('#df-export-menu');
    if (toggle && menu) {
      toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        menu.hidden = !menu.hidden;
        toggle.setAttribute('aria-expanded', String(!menu.hidden));
      });
      menu.querySelectorAll('[data-export]').forEach(b => b.addEventListener('click', async () => {
        const format = b.getAttribute('data-export');
        try {
          await DraftingApi.exportDraft(this.draftId, format, this.draftData.version);
        } catch(err) {
          window.showToast?.('Export failed', 'error');
        }
      }));
      document.addEventListener('click', (e) => {
        if (!toggle.contains(e.target)) {
          menu.hidden = true;
          toggle.setAttribute('aria-expanded', 'false');
        }
      });
    }

    // New Draft
    $('#df-new')?.addEventListener('click', () => {
      this.state = 'setup';
      this.form = this._loadDraft();
      this._renderSetup();
    });
  }
}

