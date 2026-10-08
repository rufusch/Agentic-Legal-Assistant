/* ==========================================================================
   WORKFLOW 1 — CONTRACT / CASE REVIEW VIEW (Contract Section 3)
   States: setup -> running -> report
   ========================================================================== */

import { LegalApiClient } from '../api/api-client.js';
import { ReviewApi } from '../api/review-api.js';
import { officialSourceLinks } from '../components/official-source-links.js';
import { renderCitationBadge, renderConfidenceMeter, renderWarningBox, renderPipelineTracker } from '../components/shared-ui.js';
import { Icons } from '../components/icons.js';

const DRAFT_KEY = 'caselens.review.draft';
const MAX_FOCUS = 2000;

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtDate = (iso) => { try { return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }); } catch { return iso; } };

const JURISDICTIONS = [
  ['IN', 'India (Federal)'], ['IN-MH', 'India — Maharashtra'], ['IN-DL', 'India — Delhi'],
  ['IN-KA', 'India — Karnataka'], ['IN-TN', 'India — Tamil Nadu'], ['UK', 'United Kingdom'], ['US-DE', 'United States — Delaware']
];
const RISK_HELP = {
  conservative: 'Flags issues early and rates uncertain risks as more likely.',
  balanced: 'Rates likelihood on the evidence as written.',
  aggressive: 'Rates only clearly evidenced risks as likely.'
};
const FOCUS_SUGGESTIONS = [
  'Find contradictions about payment terms and termination.',
  'Identify schedules or annexures that are referenced but missing.',
  'Summarise termination rights and exit costs.'
];

export class ReviewView {
  constructor(containerEl, onNavigate) {
    this.el = containerEl;
    this.onNavigate = onNavigate;
    this.state = 'setup';
    this.form = this._loadDraft();
    this.fieldErrors = {};
    this.formError = null;
    this.docs = [];
    this.docQuery = '';
    this.idemKey = null;
    this.job = null;
    this.sub = null;
    this.lastEventId = 0;
    this.log = [];
    this.liveWarnings = [];
    this.reviewId = null;
    this.report = null;
    this.versions = [];
    this.evidenceFilter = 'all';
    this._label = (id) => this.citMap?.[id]?.label || '?';

    document.addEventListener('click', () => {
      const m = this.el.querySelector('#rv-export-menu');
      if (m && !m.hidden) {
        m.hidden = true;
        this.el.querySelector('#rv-export-toggle')?.setAttribute('aria-expanded', 'false');
      }
    });
  }

  async render() {
    if (this.state === 'running') return this._renderRunning();
    if (this.state === 'report') return this._renderReport();
    return this._renderSetup();
  }

  _defaultForm() {
    return {
      document_ids: [],
      focus_question: '',
      options: { compare_with_governing_law: false, risk_tolerance: 'balanced', jurisdiction: 'IN', as_of_date: new Date().toISOString().slice(0, 10) }
    };
  }
  _loadDraft() {
    try {
      const d = JSON.parse(localStorage.getItem(DRAFT_KEY+':'+sessionStorage.getItem('caselens.tenant')));
      if (d && d.options && Array.isArray(d.document_ids)) return d;
    } catch { /* ignore corrupt draft */ }
    return this._defaultForm();
  }
  _saveDraft() { try { localStorage.setItem(DRAFT_KEY+':'+sessionStorage.getItem('caselens.tenant'), JSON.stringify(this.form)); } catch { /* Preserve in-memory input if storage is unavailable. */ } }

  _fieldError(name) {
    return this.fieldErrors[name] ? `<div class="rv-field-error" role="alert">${esc(this.fieldErrors[name])}</div>` : '';
  }

  /* =========================== SETUP ================================= */
  async _renderSetup() {
    const res = await LegalApiClient.listDocuments();
    this.docs = res.data;
    const readyIds = new Set(this.docs.filter(d => d.status === 'ready').map(d => d.id));
    this.form.document_ids = this.form.document_ids.filter(id => readyIds.has(id));
    const o = this.form.options;

    this.el.innerHTML = `
      <div class="view-header supplied-1cd896a576">
        <div class="view-title-group">
          <div class="rv-eyebrow">Workflow 1 &middot; Contract & Case Audit</div>
          <h1 class="supplied-bb10680361">Contract & Case Risk Audit</h1>
          <p class="view-subtitle supplied-79a028c996">
            Select documents for automated legal audit. Extract key facts, spot contradictions, verify missing schedule references, and ground every finding to source evidence.
          </p>
        </div>
      </div>

      ${this.formError ? `<div class="warning-box critical supplied-a19b0cac11" role="alert"><div class="warning-icon">${Icons.alertTriangle('', 18)}</div><div><div class="warning-title">The review could not be started</div><div class="warning-message">${esc(this.formError)}</div></div></div>` : ''}

      <!-- Landscape Compact Upload Box (Positioned above both cards) -->
      <div class="supplied-1d2d657b31">
        <div class="card rv-card supplied-f2fb085ec0">
          <div class="rv-upload-box supplied-f5d1932eff" id="rv-upload-box">
            <input type="file" id="rv-file-upload" multiple accept=".pdf,.doc,.docx" class="supplied-6aa34d7432">
            <div class="supplied-92f3ebbf29">
              <div class="supplied-b2f554c67e">
                ${Icons.upload('', 20)}
              </div>
              <div class="supplied-4555334f95">
                <div class="supplied-460544f80b">Upload Legal Documents</div>
                <div class="supplied-a11499c8c9">Drag & drop PDF, DOC, DOCX files here or click to browse</div>
              </div>
            </div>
            <button class="btn btn-secondary btn-sm supplied-b4db9caf5f">
              ${Icons.plus('', 14)} Choose Files
            </button>
          </div>
          <div id="rv-upload-status" class="supplied-9d259bd254"></div>
        </div>
      </div>

      <!-- 2-Column Setup Grid -->
      <div class="rv-setup-grid">
        <!-- Left Column: Source Document Selection -->
        <section class="card rv-card" aria-labelledby="rv-docs-title">
          <div class="rv-card-head">
            <div>
              <h3 id="rv-docs-title" class="supplied-a609928111">
                ${Icons.fileText('', 18)} 1. Select Source Documents
              </h3>
              <p class="rv-help supplied-3e967279bf">Only documents marked <strong>Ready</strong> can be audited.</p>
            </div>
            <span class="rv-count" id="rv-sel-count">${this.form.document_ids.length} selected</span>
          </div>
          
          <div class="rv-doc-toolbar">
            <div class="rv-search">
              <span class="rv-search-icon">${Icons.search('', 15)}</span>
              <input class="input" id="rv-doc-search" placeholder="Search repository..." value="${esc(this.docQuery)}" aria-label="Filter documents" />
            </div>
            <button class="btn btn-secondary btn-sm supplied-2556109043" id="rv-select-all">Select all ready</button>
            <button class="btn btn-ghost btn-sm supplied-2556109043" id="rv-clear">Clear</button>
          </div>
          
          <div class="rv-doc-list" id="rv-doc-list" role="group" aria-label="Documents">${this._docRows()}</div>
          ${this._fieldError('document_ids')}
        </section>

        <!-- Right Column: Focus Question & Analysis Parameters -->
        <section class="card rv-card" aria-labelledby="rv-settings-title">
          <h3 id="rv-settings-title" class="supplied-dd79f78297">
            ${Icons.settings('', 18)} 2. Analysis Scope & Focus
          </h3>

          <label class="rv-label supplied-aae30f4ce1" for="rv-focus">Focus Question <span class="rv-optional">Optional</span></label>
          <textarea class="textarea supplied-f60eb23cc0" id="rv-focus" rows="4" placeholder="e.g. Find contradictions regarding payment terms, notice periods, and termination liabilities...">${esc(this.form.focus_question)}</textarea>
          
          <div class="rv-field-foot supplied-413d04d4c9">
            <div>${this._fieldError('focus_question')}</div>
            <span id="rv-focus-count" class="rv-counter">${this.form.focus_question.length.toLocaleString()} / 2,000</span>
          </div>
          
          <div class="rv-suggest supplied-002dc26c47">
            ${FOCUS_SUGGESTIONS.map(s => `<button type="button" class="prompt-chip supplied-1a08a72ce9" data-suggest="${esc(s)}">${esc(s)}</button>`).join('')}
          </div>

          <div class="rv-row2 supplied-014b93e7f3">
            <div>
              <label class="rv-label supplied-aae30f4ce1" for="rv-jur">Jurisdiction</label>
              <select id="rv-jur" class="select supplied-2556109043">
                <option value="">Infer from documents</option>
                ${JURISDICTIONS.map(([v, l]) => `<option value="${v}" ${o.jurisdiction === v ? 'selected' : ''}>${l} (${v})</option>`).join('')}
              </select>
            </div>
            <div>
              <label class="rv-label supplied-aae30f4ce1" for="rv-asof">As-of Date</label>
              <input type="date" id="rv-asof" class="input supplied-2556109043" value="${esc(o.as_of_date)}" />
              ${this._fieldError('options.as_of_date')}
            </div>
          </div>

          <span class="rv-label supplied-c839ffe1e0" id="rv-risk-label">Risk Tolerance</span>
          <div class="segmented supplied-3d43560d7f" role="radiogroup" aria-labelledby="rv-risk-label">
            ${['conservative', 'balanced', 'aggressive'].map(r => `<button type="button" role="radio" aria-checked="${o.risk_tolerance === r}" class="segmented-btn ${o.risk_tolerance === r ? 'active' : ''}" data-risk="${r}">${r[0].toUpperCase() + r.slice(1)}</button>`).join('')}
          </div>
          <p class="rv-help supplied-014b93e7f3" id="rv-risk-help">${RISK_HELP[o.risk_tolerance]}</p>

          <label class="rv-switch-row" for="rv-compare">
            <span>
              <strong>Compare with governing law</strong>
              <span class="rv-help">Cross-reference findings against statutory codes in force.</span>
            </span>
            <span class="switch"><input type="checkbox" id="rv-compare" ${o.compare_with_governing_law ? 'checked' : ''} /><span class="slider"></span></span>
          </label>
          <div id="rv-infer-note">${this._inferNote()}</div>
        </section>
      </div>

      <div class="rv-actions">
        <span class="rv-help">Inputs are saved as you type. You can keep editing while an audit runs.</span>
        <div class="supplied-859a0545c5">
          <button class="btn btn-ghost supplied-2556109043" id="rv-reset">Reset</button>
          <button class="btn btn-primary supplied-ad98e6cb4b" id="rv-submit"><span>Run Audit</span>${Icons.arrowRight('', 15)}</button>
        </div>
      </div>
    `;
    this._bindSetup();
    this._updateAuditStatus();
  }

  _auditPending() {
    return this.job && !['completed', 'completed_with_warnings', 'failed', 'cancelled'].includes(this.job.status);
  }

  _updateAuditStatus() {
    if (this.state !== 'setup') return;
    let status = this.el.querySelector('#rv-audit-status');
    if (!status) {
      status = document.createElement('div');
      status.id = 'rv-audit-status';
      status.className = 'rv-note';
      status.setAttribute('aria-live', 'polite');
      this.el.querySelector('.rv-actions')?.before(status);
    }
    const pending = this._auditPending();
    const submit = this.el.querySelector('#rv-submit');
    if (submit) submit.disabled = Boolean(pending);
    if (!this.job) return;
    status.innerHTML = `<span>${pending ? 'Audit running in the background. Edits are saved for your next audit.' : 'Audit ' + esc(this.job.status) + '. Your edited inputs are saved.'}</span> <button type="button" class="btn btn-secondary" id="rv-view-audit">${this.report && !pending ? 'View report' : 'View progress'}</button>`;
    status.querySelector('#rv-view-audit').onclick = () => {
      this.state = this.report && !pending ? 'report' : 'running';
      this.render();
    };
  }

  _inferNote() {
    const o = this.form.options;
    if (!o.compare_with_governing_law || o.jurisdiction) return '';
    return `<div class="rv-note">The jurisdiction will be inferred from document metadata and flagged in the report for your confirmation.</div>`;
  }

  _docRows() {
    const q = this.docQuery.toLowerCase();
    const docs = this.docs.filter(d => !q || d.name.toLowerCase().includes(q) || (d.metadata?.title || '').toLowerCase().includes(q));
    if (!docs.length) return `<div class="rv-empty">No documents match "${esc(this.docQuery)}".</div>`;
    return docs.map(d => {
      const ready = d.status === 'ready';
      const checked = this.form.document_ids.includes(d.id);
      const m = d.metadata || {};
      return `
        <label class="rv-doc-row ${ready ? '' : 'disabled'} ${checked ? 'selected' : ''}">
          <input type="checkbox" class="rv-doc-check" value="${d.id}" ${checked ? 'checked' : ''} ${ready ? '' : 'disabled'} />
          <span class="rv-doc-icon">${Icons.fileText('', 16)}</span>
          <span class="rv-doc-main">
            <span class="rv-doc-name">${esc(d.name)}</span>
            <span class="rv-doc-meta">${esc(m.document_type || 'document')} &middot; ${esc(m.jurisdiction || '—')} &middot; ${d.page_count || 1} pages${d.ocr_used ? ' &middot; OCR' : ''}</span>
          </span>
          <span class="badge badge-${d.status}">${esc(d.status)}</span>
        </label>`;
    }).join('');
  }

  _bindSetup() {
    const $ = (s) => this.el.querySelector(s);

    const refreshList = () => {
      $('#rv-doc-list').innerHTML = this._docRows();
      $('#rv-sel-count').textContent = `${this.form.document_ids.length} selected`;
    };
    $('#rv-doc-list').addEventListener('change', (e) => {
      if (!e.target.classList.contains('rv-doc-check')) return;
      const id = e.target.value;
      this.form.document_ids = e.target.checked
        ? [...new Set([...this.form.document_ids, id])]
        : this.form.document_ids.filter(x => x !== id);
      delete this.fieldErrors.document_ids;
      this._saveDraft();
      refreshList();
    });
    $('#rv-doc-search').addEventListener('input', (e) => { this.docQuery = e.target.value; refreshList(); });
    $('#rv-select-all').addEventListener('click', () => {
      this.form.document_ids = this.docs.filter(d => d.status === 'ready').map(d => d.id);
      this._saveDraft(); refreshList();
    });
    $('#rv-clear').addEventListener('click', () => { this.form.document_ids = []; this._saveDraft(); refreshList(); });
    
    const fileInput = $('#rv-file-upload');
    const uploadBox = $('#rv-upload-box');
    const uploadStatus = $('#rv-upload-status');
    
    if (uploadBox && fileInput) {
      uploadBox.addEventListener('click', (e) => {
        if (e.target !== fileInput) fileInput.click();
      });
      
      const preventDefaults = (e) => { e.preventDefault(); e.stopPropagation(); };
      ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(evt => uploadBox.addEventListener(evt, preventDefaults));
      
      ['dragenter', 'dragover'].forEach(evt => {
        uploadBox.addEventListener(evt, () => uploadBox.style.borderColor = 'var(--brand-primary)');
      });
      ['dragleave', 'drop'].forEach(evt => {
        uploadBox.addEventListener(evt, () => uploadBox.style.borderColor = 'var(--border-medium)');
      });
      
      uploadBox.addEventListener('drop', (e) => handleUpload(e.dataTransfer.files));
      fileInput.addEventListener('change', (e) => handleUpload(e.target.files));

      const handleUpload = async (files) => {
        if (!files || !files.length) return;
        const selectedFiles = Array.from(files);
        fileInput.value = '';
        const status = document.createElement('div');
        status.setAttribute('role', 'status');
        uploadStatus.append(status);
        try {
          for (const file of selectedFiles) {
            status.textContent = `Uploading ${file.name}… You can continue editing your review.`;
            const result = await LegalApiClient.uploadDocument(file, {title:file.name, document_type:'case', jurisdiction:this.form?.options?.jurisdiction || 'IN'}, () => {
              status.textContent = `${file.name} uploaded. Reading and indexing the document… You can continue editing.`;
            });
            this.docs = [...this.docs.filter(d => d.id !== result.data.id), result.data];
            this.form.document_ids = [...new Set([...this.form.document_ids, result.data.id])];
            this._saveDraft();
            refreshList();
          }
          status.textContent = 'Documents ready and selected for review.';
          window.showToast?.('Document(s) uploaded successfully', 'success');
        } catch (err) {
          const message = err.message || 'Upload failed. Please try again.';
          window.showToast?.(message, 'error');
          status.textContent = message;
          status.setAttribute('role', 'alert');
        }
      };
    }

    const focus = $('#rv-focus');
    const counter = $('#rv-focus-count');
    const updateCounter = () => {
      const n = focus.value.length;
      counter.textContent = `${n.toLocaleString()} / 2,000`;
      counter.classList.toggle('over', n > MAX_FOCUS);
    };
    updateCounter();
    focus.addEventListener('input', () => { this.form.focus_question = focus.value; this._saveDraft(); updateCounter(); });
    this.el.querySelectorAll('[data-suggest]').forEach(b => b.addEventListener('click', () => {
      focus.value = b.getAttribute('data-suggest');
      focus.dispatchEvent(new Event('input'));
      focus.focus();
    }));

    $('#rv-jur').addEventListener('change', (e) => { this.form.options.jurisdiction = e.target.value; this._saveDraft(); $('#rv-infer-note').innerHTML = this._inferNote(); });
    $('#rv-asof').addEventListener('change', (e) => { this.form.options.as_of_date = e.target.value; this._saveDraft(); });
    $('#rv-compare').addEventListener('change', (e) => { this.form.options.compare_with_governing_law = e.target.checked; this._saveDraft(); $('#rv-infer-note').innerHTML = this._inferNote(); });
    this.el.querySelectorAll('[data-risk]').forEach(b => b.addEventListener('click', () => {
      this.form.options.risk_tolerance = b.getAttribute('data-risk');
      this.el.querySelectorAll('[data-risk]').forEach(x => {
        const on = x === b;
        x.classList.toggle('active', on);
        x.setAttribute('aria-checked', String(on));
      });
      $('#rv-risk-help').textContent = RISK_HELP[this.form.options.risk_tolerance];
      this._saveDraft();
    }));

    $('#rv-reset').addEventListener('click', () => {
      this.form = this._defaultForm(); this.fieldErrors = {}; this.formError = null;
      try{localStorage.removeItem(DRAFT_KEY+':'+sessionStorage.getItem('caselens.tenant'));}catch{}
      this._renderSetup();
    });
    $('#rv-submit').addEventListener('click', () => this._submit());
  }

  async _submit() {
    if (this._auditPending() || this.el.querySelector('#rv-submit')?.disabled) return;
    const fe = {};
    if (!this.form.document_ids.length) fe.document_ids = 'Select at least one ready document.';
    if (this.form.focus_question.length > MAX_FOCUS) fe.focus_question = 'Must be 2,000 characters or fewer.';
    this.fieldErrors = fe;
    this.formError = null;
    if (Object.keys(fe).length) return this._renderSetup();

    const btn = this.el.querySelector('#rv-submit');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-spinner"></span><span>Starting review</span>';

    this.idemKey = this.idemKey || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
    const payload = {
      document_ids: [...this.form.document_ids],
      focus_question: this.form.focus_question.trim() || undefined,
      options: { ...this.form.options, jurisdiction: this.form.options.jurisdiction || undefined }
    };
    try {
      const res = await ReviewApi.createReview(payload, this.idemKey);
      try{localStorage.removeItem(DRAFT_KEY+':'+sessionStorage.getItem('caselens.tenant'));}catch{}
      this.idemKey = null;
      this.reviewId = res.data.review_id;
      this.versions = [];
      this._startJob(res.data.job_id);
    } catch (e) {
      const err = e.error || { message: e.message || 'Unexpected error.' };
      (err.field_errors || []).forEach(f => { this.fieldErrors[f.field] = f.message; });
      this.formError = err.message + (err.retryable ? ' You can try again.' : '');
      this._renderSetup();
    }
  }

  /* =========================== RUNNING =============================== */
  _startJob(jobId) {
    this.sub?.close();
    this.state = 'setup';
    this.report = null;
    this.job = { id: jobId, status: 'queued', progress: 0.04, message: 'Review queued' };
    this.lastEventId = 0;
    this.log = [{ t: new Date(), msg: 'Review queued' }];
    this.liveWarnings = [];
    this.runError = null;
    this._renderSetup();
    this.sub = LegalApiClient.subscribeJobEvents(jobId, (evt) => this._onEvent(evt));
  }

  async _onEvent(evt) {
    if (evt.event !== 'job.snapshot') {
      if (evt.id <= this.lastEventId) return;
      this.lastEventId = evt.id;
    }
    const d = evt.data || {};
    switch (evt.event) {
      case 'job.snapshot':
        this.job = { ...this.job, ...d };
        break;
      case 'job.progress':
        this.job = { ...this.job, status: d.status, progress: d.progress, message: d.message };
        this.log.push({ t: new Date(), msg: d.status === 'cancelled' ? 'Review cancelled' : d.message });
        if (d.status === 'cancelled') this.sub?.close();
        break;
      case 'warning.created':
        if (!this.liveWarnings.some(w => w.id === d.id)) this.liveWarnings.push(d);
        break;
      case 'job.completed':
        this.sub?.close();
        this.job = { ...this.job, status: d.status || d.final_status || 'completed', progress: 1, message: 'Review complete' };
        this.log.push({ t: new Date(), msg: 'Report verified and ready' });
        await this._loadReport();
        if (this.state === 'running') {
          this.state = 'report';
          if (this._isVisible()) this._renderReport();
        } else if (this._isVisible()) this._updateAuditStatus();
        window.showToast?.('Review complete', 'success');
        return;
      case 'job.failed':
        this.sub?.close();
        this.job = { ...this.job, status: 'failed' };
        this.runError = { message: d.message || 'The review failed.', retryable: Boolean(d.retryable) };
        break;
      default:
        return;
    }
    if (this.state === 'running' && this._isVisible()) this._updateRunning();
    if (this.state === 'setup' && this._isVisible()) this._updateAuditStatus();
  }

  _isVisible() { return this.el.classList.contains('active'); }

  _renderRunning() {
    this.el.innerHTML = `
      <div class="view-header">
        <div class="view-title-group">
          <div class="rv-eyebrow">Workflow 1 &middot; Contract / Case Review</div>
          <h1>Review in progress</h1>
          <p class="view-subtitle">You can leave this page; the review continues and the report will be here when you return.</p>
        </div>
        <div id="rv-run-actions"></div>
      </div>
      <div id="rv-run-body"></div>
    `;
    this._updateRunning();
  }

  _updateRunning() {
    const actions = this.el.querySelector('#rv-run-actions');
    const body = this.el.querySelector('#rv-run-body');
    if (!actions || !body) return;
    const st = this.job.status;
    const terminal = ['cancelled', 'failed'].includes(st);

    actions.innerHTML = terminal
      ? `<div class="supplied-54da62f050">
           ${this.report ? '<button class="btn btn-secondary" id="rv-back-report">Back to report</button>' : ''}
           <button class="btn btn-primary" id="rv-back-setup">New review</button>
         </div>`
      : `<button class="btn btn-secondary" id="rv-back-setup">Edit inputs</button><button class="btn btn-danger" id="rv-cancel">Cancel review</button>`;

    body.innerHTML = `
      ${st === 'cancelled' ? `<div class="warning-box warning"><div class="warning-icon">${Icons.alertTriangle('', 18)}</div><div><div class="warning-title">Review cancelled</div><div class="warning-message">No report was produced for this run. Earlier versions, if any, are unchanged.</div></div></div>` : ''}
      ${st === 'failed' ? `<div class="warning-box critical"><div class="warning-icon">${Icons.alertTriangle('', 18)}</div><div><div class="warning-title">Review failed</div><div class="warning-message">${esc(this.runError?.message)}</div></div></div>` : ''}
      ${renderPipelineTracker(this.job)}
      <div class="rv-run-grid">
        <div class="card rv-card">
          <h4 class="rv-section-sub">Activity Timeline</h4>
          <ol class="rv-log">
            ${this.log.map(l => `<li><span class="rv-log-time">${l.t.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span><span>${esc(l.msg)}</span></li>`).join('')}
          </ol>
        </div>
        <div class="card rv-card">
          <h4 class="rv-section-sub">Issues Detected So Far</h4>
          ${this.liveWarnings.length
            ? this.liveWarnings.map(w => renderWarningBox({ ...w, citation_ids: [], resolvable: false })).join('')
            : '<p class="rv-help">Issues will appear here as claims are verified against their sources.</p>'}
        </div>
      </div>
    `;

    this.el.querySelector('#rv-cancel')?.addEventListener('click', async (e) => {
      e.currentTarget.disabled = true;
      try { await LegalApiClient.cancelJob(this.job.id); } catch { window.showToast?.('Could not cancel the review', 'error'); }
    });
    this.el.querySelector('#rv-back-setup')?.addEventListener('click', () => { this.state = 'setup'; this._renderSetup(); });
    this.el.querySelector('#rv-back-report')?.addEventListener('click', () => { this.state = 'report'; this._renderReport(); });
  }

  /* =========================== REPORT ================================ */
  async _loadReport(version) {
    const [rep, vers] = await Promise.all([
      ReviewApi.getReview(this.reviewId, version),
      ReviewApi.listVersions(this.reviewId)
    ]);
    this.report = rep.data;
    this.versions = vers.data;
    this.citMap = Object.fromEntries(this.report.citations.map(c => [c.id, c]));
    this.claimMap = Object.fromEntries(this.report.claims.map(c => [c.id, c]));
    this.evidenceFilter = 'all';
  }

  _cites(ids = []) {
    return ids.map(id => renderCitationBadge(this.citMap[id]?.label || '?', id)).join('') + officialSourceLinks(ids.map(id=>this.citMap[id]).filter(Boolean));
  }

  _sevPill(sev) {
    return `<span class="sev-pill sev-${esc(sev)}">${esc(sev)}</span>`;
  }

  _renderReport() {
    const r = this.report;
    if (!r) { this.state = 'setup'; return this._renderSetup(); }
    const docNames = r.source_document_ids.map(id => LegalApiClient._docName(id));
    const critical = r.warnings.filter(w => w.severity === 'critical');
    const other = r.warnings.filter(w => w.severity !== 'critical');
    const o = r.options || {};
    const completedVersions = this.versions.filter(v => ['completed', 'completed_with_warnings'].includes(v.status));

    this.el.innerHTML = `
      <div class="view-header supplied-1cd896a576">
        <div class="view-title-group">
          <div class="rv-eyebrow">Workflow 1 &middot; Executive Review Audit</div>
          <h1 class="supplied-bb10680361">Review Executive Audit</h1>
          <p class="view-subtitle supplied-b11c3ef352">
            Version ${r.version} &middot; ${r.source_document_ids.length} document${r.source_document_ids.length > 1 ? 's' : ''} audited &middot; ${fmtDate(r.created_at)}
          </p>
        </div>
        <div class="rv-report-actions">
          <label class="rv-version-select">
            <span>Version</span>
            <select class="select" id="rv-version">
              ${completedVersions.map(v => `<option value="${v.version}" ${v.version === r.version ? 'selected' : ''}>v${v.version} &middot; ${fmtDate(v.created_at)}</option>`).join('')}
            </select>
          </label>
          <button class="btn btn-secondary supplied-2556109043" id="rv-rerun">${Icons.search('', 14)}<span>Re-run</span></button>
          <div class="rv-export">
            <button class="btn btn-secondary supplied-2556109043" id="rv-export-toggle" aria-haspopup="menu" aria-expanded="false">${Icons.fileText('', 14)}<span>Export</span></button>
            <div class="rv-export-menu" id="rv-export-menu" role="menu" hidden>
              <button role="menuitem" data-export="pdf">PDF (Print Report)</button>
              <button role="menuitem" data-export="docx">Word Document</button>
              <button role="menuitem" data-export="json">JSON (Structured Data)</button>
            </div>
          </div>
          <button class="btn btn-primary supplied-2556109043" id="rv-new">${Icons.plus('', 14)}<span>New Audit</span></button>
        </div>
      </div>

      <!-- Executive KPI Metric Banner -->
      <div class="rv-summary">
        <div class="rv-tile">
          <div class="rv-tile-label">Overall Risk Rating</div>
          <div class="rv-tile-value supplied-4c2ba72925">${this._sevPill(r.risk_summary.overall)}</div>
        </div>
        <div class="rv-tile">
          <div class="rv-tile-label">Verification Confidence</div>
          <div class="rv-tile-value supplied-4c2ba72925">${renderConfidenceMeter(r.confidence)}</div>
          <div class="rv-tile-note">${esc(r.confidence.explanation)}</div>
        </div>
        <div class="rv-tile">
          <div class="rv-tile-label">Contradictions Found</div>
          <div class="rv-tile-num">${r.contradictions.length}</div>
        </div>
        <div class="rv-tile">
          <div class="rv-tile-label">Missing Schedules</div>
          <div class="rv-tile-num">${r.missing_information.length}</div>
        </div>
      </div>

      <!-- Audit Scope Card -->
      <div class="card rv-card rv-scope">
        <div class="rv-scope-grid">
          <div><span class="rv-tile-label">Status</span><span class="badge ${r.status === 'completed' ? 'badge-ready' : 'badge-processing'}">${r.status === 'completed' ? 'Completed' : 'Completed with warnings'}</span></div>
          <div><span class="rv-tile-label">Jurisdiction</span><span>${esc(o.jurisdiction || 'Not determined')}${o.jurisdiction_inferred ? ' <em class="rv-inferred">(inferred)</em>' : ''}</span></div>
          <div><span class="rv-tile-label">As of Date</span><span>${esc(o.as_of_date || '—')}</span></div>
          <div><span class="rv-tile-label">Risk Tolerance</span><span class="supplied-b7b96646ae">${esc(o.risk_tolerance || '—')}</span></div>
          <div><span class="rv-tile-label">Governing Law</span><span>${o.compare_with_governing_law ? 'On' : 'Off'}</span></div>
        </div>
        ${r.focus_question ? `<div class="rv-focus-quote"><span class="rv-tile-label">Focus Question</span><p>${esc(r.focus_question)}</p></div>` : ''}
        <div class="rv-docs-line"><span class="rv-tile-label">Audited Documents</span>
          <ul>${docNames.map(n => `<li>${Icons.fileText('', 13)}<span>${esc(n)}</span></li>`).join('')}</ul>
        </div>
      </div>

      ${critical.length ? `<section class="rv-section" aria-label="Critical warnings">${critical.map(w => renderWarningBox(w, this._label)).join('')}</section>` : ''}

      <!-- Sticky Tab Bar -->
      <nav class="rv-tabs" aria-label="Report sections">
        <a href="#rv-sec-risk">Risk Summary</a>
        <a href="#rv-sec-facts">Key Facts <span>${r.key_facts.length}</span></a>
        <a href="#rv-sec-contra">Contradictions <span>${r.contradictions.length}</span></a>
        <a href="#rv-sec-missing">Missing Info <span>${r.missing_information.length}</span></a>
        <a href="#rv-sec-evidence">Evidence <span>${r.relevant_evidence.length}</span></a>
        <a href="#rv-sec-claims">Ledger <span>${r.claims.length}</span></a>
        ${other.length ? `<a href="#rv-sec-warnings">Notices <span>${other.length}</span></a>` : ''}
      </nav>

      ${this._secRisk(r)}
      ${this._secFacts(r)}
      ${this._secContradictions(r)}
      ${this._secMissing(r)}
      ${this._secEvidence(r)}
      ${this._secClaims(r)}
      ${other.length ? `<section class="rv-section" id="rv-sec-warnings"><h2 class="rv-section-title">Notices</h2>${other.map(w => renderWarningBox(w, this._label)).join('')}</section>` : ''}

      <p class="rv-disclaimer">This executive report is generated from verified tenant documents${o.compare_with_governing_law ? ' and statutory provisions' : ''}. Every finding links to an exact source passage; click a citation to inspect it.</p>
      <div id="rv-modal-root"></div>
    `;
    this._bindReport();
  }

  _secRisk(r) {
    const rs = r.risk_summary;
    return `
      <section class="rv-section" id="rv-sec-risk">
        <h2 class="rv-section-title">Risk Summary & Analysis</h2>
        <div class="card rv-card">
          <p class="rv-rationale">${esc(rs.rationale)}</p>
          ${rs.items.length ? `
            <table class="rv-table">
              <thead><tr><th>Identified Risk</th><th>Severity</th><th>Likelihood</th><th>Proven Sources</th></tr></thead>
              <tbody>${rs.items.map(i => `
                <tr><td class="supplied-b0ebcb0c8c">${esc(i.risk)}</td><td>${this._sevPill(i.severity)}</td><td><span class="rv-like rv-like-${esc(i.likelihood)}">${esc(i.likelihood)}</span></td><td>${this._cites(i.citation_ids)}</td></tr>`).join('')}
              </tbody>
            </table>` : ''}
        </div>
      </section>`;
  }

  _secFacts(r) {
    const STATUS = { supported: 'Supported', partially_supported: 'Partially supported', unsupported: 'Unsupported', contradicted: 'Contradicted' };
    return `
      <section class="rv-section" id="rv-sec-facts">
        <h2 class="rv-section-title">Key Facts Ledger</h2>
        <div class="card rv-card supplied-6fe40c4f78">
          ${r.key_facts.length ? `
            <table class="rv-table">
              <thead><tr><th class="supplied-56d1e02045">Fact Label</th><th>Extracted Value</th><th>Verification Status</th><th>Verified Source</th></tr></thead>
              <tbody>${r.key_facts.map(f => {
                const c = this.claimMap[f.claim_id];
                const st = c?.verification_status || 'supported';
                return `<tr><td class="rv-strong">${esc(f.label)}</td><td>${esc(f.value)}</td><td><span class="claim-status ${st}">${STATUS[st]}</span></td><td>${this._cites(f.citation_ids)}</td></tr>`;
              }).join('')}</tbody>
            </table>` : '<p class="rv-empty-block">No key facts extracted.</p>'}
        </div>
      </section>`;
  }

  _secContradictions(r) {
    return `
      <section class="rv-section" id="rv-sec-contra">
        <h2 class="rv-section-title">Detected Contradictions</h2>
        ${r.contradictions.length ? r.contradictions.map(c => `
          <article class="card rv-card rv-contra">
            <header class="rv-contra-head">
              <div><h3>${esc(c.topic)}</h3>${this._sevPill(c.severity)}</div>
              ${renderConfidenceMeter(c.confidence)}
            </header>
            <p class="rv-contra-desc">${esc(c.description)}</p>
            <div class="rv-sides">
              ${c.sides.map((s, i) => `
                <div class="rv-side">
                  <div class="rv-side-label">Position ${String.fromCharCode(65 + i)}</div>
                  <p>${esc(s.statement)}</p>
                  <div class="claim-citations">${this._cites(s.citation_ids)}</div>
                </div>`).join('<div class="rv-vs" aria-hidden="true">VS</div>')}
            </div>
            ${c.legal_effect ? `<div class="rv-kv"><span class="rv-tile-label">Legal Effect</span><p>${esc(c.legal_effect)} ${this._lawCites(r)}</p></div>` : ''}
            ${c.resolution ? `<div class="rv-kv"><span class="rv-tile-label">Suggested Next Step</span><p>${esc(c.resolution)}</p></div>` : ''}
            <p class="rv-help supplied-b48eab0cb6">${esc(c.confidence.explanation)}</p>
          </article>`).join('') : '<div class="card rv-card"><p class="rv-empty-block">No contradictions detected between selected documents.</p></div>'}
      </section>`;
  }

  _lawCites(r) {
    const law = r.relevant_evidence.filter(e => e.category === 'law').flatMap(e => e.citation_ids);
    return this._cites([...new Set(law)].filter(id => this.citMap[id]?.document_id?.startsWith('law-')));
  }

  _secMissing(r) {
    return `
      <section class="rv-section" id="rv-sec-missing">
        <h2 class="rv-section-title">Missing Information & Unresolved Schedules</h2>
        ${r.missing_information.length ? `<div class="rv-missing-grid">${r.missing_information.map(m => `
          <article class="card rv-card rv-missing rv-missing-${esc(m.severity)}">
            <header><h3>${esc(m.item)}</h3>${this._sevPill(m.severity)}</header>
            <div class="rv-kv"><span class="rv-tile-label">Why It Matters</span><p>${esc(m.why_it_matters)}</p></div>
            ${m.suggested_action ? `<div class="rv-kv"><span class="rv-tile-label">Suggested Action</span><p>${esc(m.suggested_action)}</p></div>` : ''}
          </article>`).join('')}</div>` : '<div class="card rv-card"><p class="rv-empty-block">No missing material detected.</p></div>'}
      </section>`;
  }

  _secEvidence(r) {
    const cats = ['all', 'clause', 'fact', 'law', 'precedent'];
    const counts = Object.fromEntries(cats.map(c => [c, c === 'all' ? r.relevant_evidence.length : r.relevant_evidence.filter(e => e.category === c).length]));
    const list = r.relevant_evidence.filter(e => this.evidenceFilter === 'all' || e.category === this.evidenceFilter);
    return `
      <section class="rv-section" id="rv-sec-evidence">
        <div class="rv-section-head">
          <h2 class="rv-section-title">Relevant Evidence Index</h2>
          <div class="segmented segmented-sm" role="tablist">
            ${cats.map(c => `<button class="segmented-btn ${this.evidenceFilter === c ? 'active' : ''}" data-evf="${c}" ${counts[c] || c === 'all' ? '' : 'disabled'}>${c[0].toUpperCase() + c.slice(1)} (${counts[c]})</button>`).join('')}
          </div>
        </div>
        <div class="rv-evidence-grid" id="rv-evidence-grid">
          ${list.map(e => `
            <article class="card rv-card rv-evidence">
              <span class="rv-cat rv-cat-${esc(e.category)}">${esc(e.category)}</span>
              <h4>${esc(e.title)}</h4>
              <p>${esc(e.summary)}</p>
              <div class="claim-citations">${this._cites(e.citation_ids)}</div>
            </article>`).join('') || '<p class="rv-empty-block">No evidence in this category.</p>'}
        </div>
      </section>`;
  }

  _secClaims(r) {
    const STATUS = { supported: 'Supported', partially_supported: 'Partially supported', unsupported: 'Unsupported', contradicted: 'Contradicted' };
    return `
      <section class="rv-section" id="rv-sec-claims">
        <h2 class="rv-section-title">Verification Ledger</h2>
        <p class="rv-help supplied-413d04d4c9">Every statement in this report was verified against quoted source passages.</p>
        <div class="card rv-card supplied-6fe40c4f78">
          <table class="rv-table">
            <thead><tr><th>Statement</th><th>Status</th><th>Confidence</th><th>Sources</th></tr></thead>
            <tbody>${r.claims.map(c => `
              <tr><td>${esc(c.text)}${c.warning ? `<div class="rv-help">${esc(c.warning)}</div>` : ''}</td>
                  <td><span class="claim-status ${c.verification_status}">${STATUS[c.verification_status]}</span></td>
                  <td class="rv-mono">${Math.round(c.confidence * 100)}%</td>
                  <td>${this._cites(c.citation_ids)}</td></tr>`).join('')}
            </tbody>
          </table>
        </div>
      </section>`;
  }

  _bindReport() {
    const $ = (s) => this.el.querySelector(s);

    $('#rv-version').addEventListener('change', async (e) => {
      try { await this._loadReport(Number(e.target.value)); this._renderReport(); }
      catch (err) { window.showToast?.(err.error?.message || 'Could not load version', 'error'); }
    });
    $('#rv-new').addEventListener('click', () => { this.state = 'setup'; this.form = this._loadDraft(); this._renderSetup(); });
    $('#rv-rerun').addEventListener('click', () => this._openRerun());

    const toggle = $('#rv-export-toggle');
    const menu = $('#rv-export-menu');
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
      toggle.setAttribute('aria-expanded', String(!menu.hidden));
    });
    menu.querySelectorAll('[data-export]').forEach(b => b.addEventListener('click', () => this._export(b.getAttribute('data-export'))));

    this.el.querySelectorAll('[data-evf]').forEach(b => b.addEventListener('click', () => {
      this.evidenceFilter = b.getAttribute('data-evf');
      this._rebindEvidence();
    }));

    this.el.querySelectorAll('.rv-tabs a').forEach(a => a.addEventListener('click', (e) => {
      e.preventDefault();
      this.el.querySelector(a.getAttribute('href'))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
  }

  _rebindEvidence() {
    const sec = this.el.querySelector('#rv-sec-evidence');
    sec.outerHTML = this._secEvidence(this.report);
    this.el.querySelectorAll('[data-evf]').forEach(x => x.addEventListener('click', () => { this.evidenceFilter = x.getAttribute('data-evf'); this._rebindEvidence(); }));
  }

  /* ------------------------- Re-run modal ---------------------------- */
  _openRerun() {
    const r = this.report;
    const o = { ...this.form.options, ...(r.options || {}) };
    const jur = o.jurisdiction_inferred ? '' : (o.jurisdiction || '');
    const root = this.el.querySelector('#rv-modal-root');
    root.innerHTML = `
      <div class="modal-backdrop open" id="rv-rerun-modal" role="dialog" aria-modal="true" aria-labelledby="rv-rerun-title">
        <div class="modal-card supplied-730cac87c6">
          <div class="modal-header">
            <h3 id="rv-rerun-title" class="supplied-1d2e33063c">Re-run Audit</h3>
            <button class="drawer-close" id="rv-rerun-close" aria-label="Close">&times;</button>
          </div>
          <div class="modal-body">
            <p class="rv-help supplied-726cf47beb">A new version is created with the same documents. Version ${r.version} stays unchanged.</p>
            <label class="rv-label" for="rr-focus">Focus Question</label>
            <textarea class="textarea" id="rr-focus" rows="3">${esc(r.focus_question || '')}</textarea>
            <div class="rv-field-foot"><div id="rr-focus-err"></div><span id="rr-count" class="rv-counter"></span></div>
            <div class="rv-row2">
              <div>
                <label class="rv-label" for="rr-jur">Jurisdiction</label>
                <select class="select" id="rr-jur">
                  <option value="">Infer from documents</option>
                  ${JURISDICTIONS.map(([v, l]) => `<option value="${v}" ${jur === v ? 'selected' : ''}>${l} (${v})</option>`).join('')}
                </select>
              </div>
              <div>
                <label class="rv-label" for="rr-asof">As-of Date</label>
                <input type="date" class="input" id="rr-asof" value="${esc(o.as_of_date)}" />
              </div>
            </div>
            <label class="rv-label" for="rr-risk">Risk Tolerance</label>
            <select class="select" id="rr-risk">
              ${['conservative', 'balanced', 'aggressive'].map(x => `<option value="${x}" ${o.risk_tolerance === x ? 'selected' : ''}>${x[0].toUpperCase() + x.slice(1)}</option>`).join('')}
            </select>
            <label class="rv-switch-row supplied-9a7472a9ec" for="rr-compare">
              <span><strong>Compare with governing law</strong></span>
              <span class="switch"><input type="checkbox" id="rr-compare" ${o.compare_with_governing_law ? 'checked' : ''} /><span class="slider"></span></span>
            </label>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" id="rr-cancel">Cancel</button>
            <button class="btn btn-primary" id="rr-submit">Start Re-run</button>
          </div>
        </div>
      </div>
    `;

    const close = () => { root.innerHTML = ''; };
    root.querySelector('#rv-rerun-close').addEventListener('click', close);
    root.querySelector('#rr-cancel').addEventListener('click', close);

    root.querySelector('#rr-submit').addEventListener('click', async () => {
      const q = root.querySelector('#rr-focus').value;
      if (q.length > MAX_FOCUS) {
        root.querySelector('#rr-focus-err').innerHTML = '<div class="rv-field-error">Must be 2,000 characters or fewer.</div>';
        return;
      }
      const payload = {
        document_ids: [...r.source_document_ids],
        focus_question: q.trim() || undefined,
        options: {
          compare_with_governing_law: root.querySelector('#rr-compare').checked,
          risk_tolerance: root.querySelector('#rr-risk').value,
          jurisdiction: root.querySelector('#rr-jur').value || undefined,
          as_of_date: root.querySelector('#rr-asof').value
        }
      };
      close();
      const key = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
      try {
        const res = await ReviewApi.createReview(payload, key);
        this.reviewId = res.data.review_id;
        this._startJob(res.data.job_id);
      } catch (err) {
        window.showToast?.(err.error?.message || 'Could not start re-run', 'error');
      }
    });
  }

  async _export(fmt) {
    try {
      await ReviewApi.exportReview(this.reviewId, fmt, this.report.version);
    } catch (e) {
      window.showToast?.('Export failed.', 'error');
    }
  }

  _downloadBlob(blob, name) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  }
}
