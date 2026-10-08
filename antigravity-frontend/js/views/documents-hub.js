/* ==========================================================================
   SHARED DOCUMENT MANAGEMENT HUB VIEW
   Contract Section 2.5: /documents API (Upload, Index, Chunk inspection)
   ========================================================================== */

import { LegalApiClient, escapeHtml } from '../api/api-client.js';
import { CitationDrawer } from '../components/citation-drawer.js';

export class DocumentsHubView {
  constructor(containerEl) {
    this.container = containerEl;
    this.filterStatus = 'all';
    this.searchQuery = '';
    this.documents = [];
    this.uploadModalEl = null;
  }

  async render() {
    await this.loadDocuments();

    this.container.innerHTML = `
      <div class="view-header">
        <div class="view-title-group">
          <div style="display: flex; align-items: center; gap: 0.65rem; margin-bottom: 0.25rem;">
            <h1>Legal Document Repository</h1>
            
          </div>
          <p class="view-subtitle">Manage legal matters, executed contracts, scanned annexures, and statutory precedents for grounded AI retrieval.</p>
        </div>
        <button class="btn btn-primary" id="btn-open-upload-modal">
          Upload Legal Document
        </button>
      </div>

      <!-- Filter and Search Toolbar -->
      <div class="card" style="padding: 1rem 1.25rem; margin-bottom: 1.5rem; display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;">
        <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
          <span style="font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase; font-weight: 700; margin-right: 0.25rem;">Status Filter:</span>
          <button class="btn btn-sm ${this.filterStatus === 'all' ? 'btn-secondary' : 'btn-ghost'}" data-filter="all">All Documents (${this.documents.length})</button>
          <button class="btn btn-sm ${this.filterStatus === 'ready' ? 'btn-secondary' : 'btn-ghost'}" data-filter="ready">Ready (${this.documents.filter(d => d.status === 'ready').length})</button>
          <button class="btn btn-sm ${this.filterStatus === 'processing' ? 'btn-secondary' : 'btn-ghost'}" data-filter="processing">Processing (${this.documents.filter(d => d.status === 'processing').length})</button>
          <button class="btn btn-sm ${this.filterStatus === 'ocr' ? 'btn-secondary' : 'btn-ghost'}" data-filter="ocr">OCR Used (${this.documents.filter(d => d.ocr_used).length})</button>
        </div>

        <div style="width: 280px; position: relative;">
          <input type="text" class="input" id="input-search-docs" placeholder="Search by title, name..." value="${this.searchQuery}" style="padding-left: 2rem; font-size: 0.85rem;" />
          <span style="position: absolute; left: 0.75rem; top: 50%; transform: translateY(-50%); color: var(--text-dim); font-size: 0.85rem;">🔍</span>
        </div>
      </div>

      <!-- Documents Table / Grid -->
      <div class="card" style="padding: 0; overflow: hidden;">
        <div style="overflow-x: auto;">
          <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 0.875rem;">
            <thead>
              <tr style="border-bottom: 1px solid var(--border-medium); background: #FAF5ED; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); font-weight: 700;">
                <th style="padding: 1rem 1.25rem;">Document Name & Title</th>
                <th style="padding: 1rem 1rem;">Type & Jurisdiction</th>
                <th style="padding: 1rem 1rem;">Pages / OCR</th>
                <th style="padding: 1rem 1rem;">Pipeline Status</th>
                <th style="padding: 1rem 1rem;">Date</th>
                <th style="padding: 1rem 1.25rem; text-align: right;">Action</th>
              </tr>
            </thead>
            <tbody id="documents-table-body">
              ${this._renderTableRows()}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Upload Modal Placeholder -->
      <div id="upload-modal-container"></div>
    `;

    this._bindEvents();
  }

  async loadDocuments() {
    const res = await LegalApiClient.listDocuments();
    this.documents = res.data;
  }

  _renderTableRows() {
    let filtered = [...this.documents];

    if (this.filterStatus === 'ready') {
      filtered = filtered.filter(d => d.status === 'ready');
    } else if (this.filterStatus === 'processing') {
      filtered = filtered.filter(d => d.status === 'processing');
    } else if (this.filterStatus === 'ocr') {
      filtered = filtered.filter(d => d.ocr_used);
    }

    if (this.searchQuery) {
      const q = this.searchQuery.toLowerCase();
      filtered = filtered.filter(d => 
        d.name.toLowerCase().includes(q) || 
        (d.metadata?.title && d.metadata.title.toLowerCase().includes(q))
      );
    }

    if (filtered.length === 0) {
      return `
        <tr>
          <td colspan="6" style="padding: 3rem; text-align: center; color: var(--text-muted);">
            No documents matching filter criteria.
          </td>
        </tr>
      `;
    }

    return filtered.map(doc => {
      const meta = doc.metadata || {};
      const statusBadge = `
        <span class="badge badge-${doc.status}">
          ${doc.status === 'processing' ? '<span style="display: inline-block; width: 6px; height: 6px; background: currentColor; border-radius: 50%; margin-right: 4px;"></span>' : ''}
          ${doc.status}
        </span>
      `;

      return `
        <tr style="border-bottom: 1px solid var(--border-subtle); transition: background 0.15s ease;" onmouseover="this.style.background='#F8F3EA'" onmouseout="this.style.background='transparent'">
          <td style="padding: 1rem 1.25rem;">
            <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 0.15rem;">
              ${escapeHtml(doc.name)}
            </div>
            <div style="font-size: 0.78rem; color: var(--text-muted);">
              ${escapeHtml(meta.title || 'Legal Document')}
            </div>
          </td>

          <td style="padding: 1rem 1rem;">
            <span style="display: inline-block; padding: 0.15rem 0.45rem; background: rgba(255,255,255,0.05); border-radius: var(--radius-sm); font-size: 0.75rem; text-transform: uppercase;">
              ${escapeHtml(meta.document_type || 'Unclassified')}
            </span>
            <span style="font-size: 0.75rem; color: var(--text-dim); margin-left: 0.35rem;">
              ${escapeHtml(meta.jurisdiction || 'Unknown')}
            </span>
          </td>

          <td style="padding: 1rem 1rem;">
            <span>${doc.page_count ? doc.page_count+' pages' : 'Page anchors unavailable'}</span>
            ${doc.ocr_used ? '<span class="badge badge-ocr" style="margin-left: 0.4rem;">OCR</span>' : ''}
          </td>

          <td style="padding: 1rem 1rem;">
            ${statusBadge}
          </td>

          <td style="padding: 1rem 1rem; color: var(--text-muted); font-size: 0.8rem;">
            ${escapeHtml(meta.document_date || doc.created_at.split('T')[0])}
          </td>

          <td style="padding: 1rem 1.25rem; text-align: right;">
            <button class="btn btn-secondary btn-sm btn-inspect-doc" data-doc-id="${doc.id}">
              🔍 Inspect Source
            </button>
          </td>
        </tr>
      `;
    }).join('');
  }

  _bindEvents() {
    // Filter buttons
    this.container.querySelectorAll('[data-filter]').forEach(btn => {
      btn.addEventListener('click', () => {
        this.filterStatus = btn.getAttribute('data-filter');
        this.render();
      });
    });

    // Search input
    const searchInput = this.container.querySelector('#input-search-docs');
    searchInput?.addEventListener('input', (e) => {
      this.searchQuery = e.target.value;
      const tbody = this.container.querySelector('#documents-table-body');
      if (tbody) tbody.innerHTML = this._renderTableRows();
      this._bindInspectButtons();
    });

    // Upload Modal trigger
    this.container.querySelector('#btn-open-upload-modal')?.addEventListener('click', () => {
      this._openUploadModal();
    });

    this._bindInspectButtons();
  }

  _bindInspectButtons() {
    this.container.querySelectorAll('.btn-inspect-doc').forEach(btn => {
      btn.addEventListener('click', async () => {
        const docId = btn.getAttribute('data-doc-id');
        // Open Citation Drawer with sample citation or chunk from doc
        CitationDrawer.open(docId);
      });
    });
  }

  /**
   * Two-step Upload Wizard:
   * 1. POST /documents/uploads (file_name, content_type, size_bytes, sha256)
   * 2. Direct upload simulation
   * 3. POST /documents/{id}/complete (metadata)
   */
  _openUploadModal() {
    const modalContainer = this.container.querySelector('#upload-modal-container');
    modalContainer.innerHTML = `
      <div class="modal-backdrop open" id="upload-modal-root">
        <div class="modal-card">
          <div class="modal-header">
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              <h3 style="font-size: 1.1rem;">Upload Legal Document</h3>
            </div>
            <button class="drawer-close" id="btn-close-modal">&times;</button>
          </div>

          <div class="modal-body" id="modal-wizard-body">
            <!-- Step 1: File Selection -->
            <div id="upload-step-1">
              <div class="upload-dropzone" id="dropzone-area">
                <div class="upload-icon" style="display: flex; justify-content: center; color: var(--accent-gold); margin-bottom: 0.5rem;">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><polyline points="17 14 12 9 7 14"/><line x1="12" y1="9" x2="12" y2="20"/></svg>
                </div>
                <div style="font-weight: 600; font-size: 0.95rem; margin-bottom: 0.35rem;">
                  Drag & Drop legal file here, or click to browse
                </div>
                <div style="font-size: 0.8rem; color: var(--text-dim);">
                  PDF, DOCX, TXT, images · max 25 MB. Legacy DOC requires server support.
                </div>
                <input type="file" id="file-picker-input" style="display: none;" accept=".pdf,.docx,.txt,.doc,.png,.jpg,.jpeg,.tif,.tiff" />
              </div>

              <div id="selected-file-info" style="display: none; background: #FDF6EC; border: 1px solid var(--accent-gold); border-radius: var(--radius-md); padding: 0.85rem 1rem; margin-bottom: 1.25rem;">
                <div style="font-size: 0.85rem; font-weight: 600; color: var(--text-primary);" id="selected-file-name">filename.pdf</div>
                <div style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono); margin-top: 0.2rem;" id="selected-file-meta">
                  Size: 2.4 MB | SHA256: calculating...
                </div>
              </div>

              <!-- Metadata Form Fields -->
              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
                <div>
                  <label style="display: block; font-size: 0.75rem; text-transform: uppercase; color: var(--text-dim); font-weight: 700; margin-bottom: 0.35rem;">Document Title</label>
                  <input type="text" class="input" id="upload-meta-title" placeholder="e.g. Non-Disclosure Agreement" />
                </div>
                <div>
                  <label style="display: block; font-size: 0.75rem; text-transform: uppercase; color: var(--text-dim); font-weight: 700; margin-bottom: 0.35rem;">Document Type</label>
                  <select class="select" id="upload-meta-type">
                    <option value="contract">Commercial Contract</option>
                    <option value="judgment">Court Judgment / Precedent</option>
                    <option value="statute">Statute / Regulation</option>
                    <option value="annexure">Annexure / Schedule</option>
                    <option value="sow">Statement of Work</option>
                  </select>
                </div>
                <div>
                  <label style="display: block; font-size: 0.75rem; text-transform: uppercase; color: var(--text-dim); font-weight: 700; margin-bottom: 0.35rem;">Jurisdiction</label>
                  <select class="select" id="upload-meta-jurisdiction">
                    <option value="IN-MH">India - Maharashtra (IN-MH)</option>
                    <option value="IN">India - Federal / Supreme Court (IN)</option>
                    <option value="US-DE">United States - Delaware (US-DE)</option>
                    <option value="UK">United Kingdom (UK)</option>
                  </select>
                </div>
                <div>
                  <label style="display: block; font-size: 0.75rem; text-transform: uppercase; color: var(--text-dim); font-weight: 700; margin-bottom: 0.35rem;">Document Date</label>
                  <input type="text" class="input" id="upload-meta-court" placeholder="Court / authority, if applicable"><input type="date" class="input" id="upload-meta-date"  />
                </div>
              </div>
            </div>

            <!-- Step 2: Upload & Indexing Progress -->
            <div id="upload-step-2" style="display: none; text-align: center; padding: 2rem 1rem;">
              <div style="display: inline-block; width: 36px; height: 36px; border: 3px solid var(--border-medium); border-top-color: var(--accent-gold); border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 1rem;"></div>
              <h4 style="margin-bottom: 0.4rem;" id="upload-progress-title">Uploading & Initiating Pipeline...</h4>
              <p style="font-size: 0.85rem; color: var(--text-muted);" id="upload-progress-desc">
                Submitting sha256 payload, receiving upload URL, and indexing chunks.
              </p>
            </div>
          </div>

          <div class="modal-footer" id="modal-footer-btns">
            <button class="btn btn-ghost" id="btn-cancel-modal">Cancel</button>
            <button class="btn btn-primary" id="btn-submit-upload" disabled>Proceed with Upload</button>
          </div>
        </div>
      </div>
    `;

    const dropzone = modalContainer.querySelector('#dropzone-area');
    const filePicker = modalContainer.querySelector('#file-picker-input');
    const btnSubmit = modalContainer.querySelector('#btn-submit-upload');
    const fileInfoBox = modalContainer.querySelector('#selected-file-info');
    const fileNameEl = modalContainer.querySelector('#selected-file-name');
    const fileMetaEl = modalContainer.querySelector('#selected-file-meta');
    const titleInput = modalContainer.querySelector('#upload-meta-title');

    let selectedFile = null;

    dropzone.addEventListener('click', () => filePicker.click());
    filePicker.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        selectedFile = e.target.files[0];
        fileInfoBox.style.display = 'block';
        fileNameEl.textContent = selectedFile.name;
        titleInput.value = selectedFile.name.replace(/\.[^/.]+$/, "");
        
        fileMetaEl.textContent = `Size: ${(selectedFile.size / 1024).toFixed(1)} KB · SHA256 is computed from the file during upload`;
        btnSubmit.disabled = false;
      }
    });

    // Close buttons
    modalContainer.querySelector('#btn-close-modal')?.addEventListener('click', () => { modalContainer.innerHTML = ''; });
    modalContainer.querySelector('#btn-cancel-modal')?.addEventListener('click', () => { modalContainer.innerHTML = ''; });

    // Submit handler (Contract 2.5)
    btnSubmit.addEventListener('click', async () => {
      if (!selectedFile) return;

      const step1 = modalContainer.querySelector('#upload-step-1');
      const step2 = modalContainer.querySelector('#upload-step-2');
      const footerBtns = modalContainer.querySelector('#modal-footer-btns');

      step1.style.display = 'none';
      step2.style.display = 'block';
      footerBtns.style.display = 'none';

      try {
        modalContainer.querySelector('#upload-progress-title').textContent = 'Uploading and parsing source document…';
        await LegalApiClient.uploadDocument(selectedFile, {
          title: titleInput.value || selectedFile.name,
          document_type: modalContainer.querySelector('#upload-meta-type').value,
          jurisdiction: modalContainer.querySelector('#upload-meta-jurisdiction').value,
          document_date: modalContainer.querySelector('#upload-meta-date').value,
          decided_at: modalContainer.querySelector('#upload-meta-type').value==='judgment' ? modalContainer.querySelector('#upload-meta-date').value || undefined : undefined,
          effective_from: modalContainer.querySelector('#upload-meta-type').value==='statute' ? modalContainer.querySelector('#upload-meta-date').value || undefined : undefined,
          court:modalContainer.querySelector('#upload-meta-court').value || undefined
        });
        window.app?.updateDocBadgeCount();

        window.showToast("Document registered and queued for indexing", "success");
        setTimeout(async () => {
          modalContainer.innerHTML = '';
          await this.render();
        }, 800);

      } catch (err) {
        console.error(err);
        modalContainer.querySelector('#upload-progress-title').textContent = "Upload Error";
        modalContainer.querySelector('#upload-progress-desc').textContent = err.error?.message || "Failed to process document upload.";
      }
    });
  }
}
