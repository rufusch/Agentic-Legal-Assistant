/* ==========================================================================
   SHARED DOCUMENT MANAGEMENT HUB VIEW
   Contract Section 2.5: /documents API (Upload, Index, Chunk inspection)
   ========================================================================== */

import { LegalApiClient, escapeHtml, request } from '../api/api-client.js';
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
          <div class="supplied-29ced55988">
            <h1>Your documents</h1>
            
          </div>
          <p class="view-subtitle">Upload a file and wait for Ready. You can then review it or ask questions about it.</p>
        </div>
        <button class="btn btn-primary" id="btn-open-upload-modal">
          Upload document
        </button>
      </div>

      <!-- Filter and Search Toolbar -->
      <div class="card supplied-62db54a033">
        <div class="supplied-e6a777a22e">
          <span class="supplied-3b6f4c82cc">Status Filter:</span>
          <button class="btn btn-sm ${this.filterStatus === 'all' ? 'btn-secondary' : 'btn-ghost'}" data-filter="all">All Documents (${this.documents.length})</button>
          <button class="btn btn-sm ${this.filterStatus === 'ready' ? 'btn-secondary' : 'btn-ghost'}" data-filter="ready">Ready (${this.documents.filter(d => d.status === 'ready').length})</button>
          <button class="btn btn-sm ${this.filterStatus === 'processing' ? 'btn-secondary' : 'btn-ghost'}" data-filter="processing">Processing (${this.documents.filter(d => d.status === 'processing').length})</button>
          <button class="btn btn-sm ${this.filterStatus === 'ocr' ? 'btn-secondary' : 'btn-ghost'}" data-filter="ocr">OCR Used (${this.documents.filter(d => d.ocr_used).length})</button>
        </div>

        <div class="supplied-31e31c6579">
          <input type="text" class="input supplied-c8ce8e207b" id="input-search-docs" placeholder="Search by title, name..." value="${escapeHtml(this.searchQuery)}" />
          <span class="supplied-baa4f14ef3">🔍</span>
        </div>
      </div>

      <!-- Documents Table / Grid -->
      <div class="card supplied-6fe40c4f78">
        <div class="supplied-aeadbd0923">
          <table class="supplied-253f8bb56a">
            <thead>
              <tr class="supplied-da6cf34ceb">
                <th class="supplied-0d5984eb4a">Document Name & Title</th>
                <th class="supplied-35d933f2d9">Type & Jurisdiction</th>
                <th class="supplied-35d933f2d9">Pages / OCR</th>
                <th class="supplied-35d933f2d9">Status</th>
                <th class="supplied-35d933f2d9">Date</th>
                <th class="supplied-8def568bda">Action</th>
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
    const starter=document.createElement('button');starter.className='btn btn-secondary';starter.textContent='Load official starter sources';
    this.container.querySelector('#btn-open-upload-modal').after(starter);
    starter.onclick=async()=>{
      starter.disabled=true;starter.textContent='Loading and parsing official sources…';
      try{
        const corpus=(await request('starter-corpus')).data;
        const known=new Set(this.documents.filter(d=>d.status==='ready').map(d=>d.sha256));
        for(const item of corpus.items){
          if(known.has(item.sha256))continue;
          const response=await fetch(new URL(item.download_url,window.CASELENS_API_BASE||location.origin),{redirect:'error'});if(!response.ok)throw new Error('Starter source unavailable.');
          const blob=await response.blob();const file=new File([blob],item.path,{type:'application/pdf'});
          const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());const actual=[...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join('');
          if(actual!==item.sha256)throw new Error('Starter source checksum mismatch.');
          await LegalApiClient.uploadDocument(file,item.metadata);
        }
        window.showToast?.('Official source snapshots are ready. Currency and applicability still require review.','success');window.app.updateDocBadgeCount();await this.render();
      }catch(e){window.showToast?.(e.message,'error');starter.disabled=false;starter.textContent='Load official starter sources';}
    };
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
          <td colspan="6" class="supplied-4732d327dd">
            No documents matching filter criteria.
          </td>
        </tr>
      `;
    }

    return filtered.map(doc => {
      const meta = doc.metadata || {};
      const statusBadge = `
        <span class="badge badge-${doc.status}">
          ${doc.status === 'processing' ? '<span class="supplied-9b0ef32d63"></span>' : ''}
          ${doc.status}
        </span>
      `;

      return `
        <tr  class="supplied-28bf3a0686">
          <td class="supplied-0d5984eb4a">
            <div class="supplied-1902a4f5b6">
              ${escapeHtml(doc.name)}
            </div>
            <div class="supplied-e4ec51f301">
              ${escapeHtml(meta.title || 'Legal Document')}
            </div>
          </td>

          <td class="supplied-35d933f2d9">
            <span class="supplied-e93728de3a">
              ${escapeHtml(meta.document_type || 'Unclassified')}
            </span>
            <span class="supplied-d91acfa73b">
              ${escapeHtml(meta.jurisdiction || 'Unknown')}
            </span>
          </td>

          <td class="supplied-35d933f2d9">
            <span>${doc.page_count ? doc.page_count+' pages' : 'Page anchors unavailable'}</span>
            ${doc.ocr_used ? '<span class="badge badge-ocr supplied-3394cd4842">OCR</span>' : ''}
          </td>

          <td class="supplied-35d933f2d9">
            ${statusBadge}
            ${doc.failure ? `<p role="alert">${escapeHtml(doc.failure.message || 'Processing failed. Try uploading a readable copy.')}</p>` : ''}
          </td>

          <td class="supplied-1c77588258">
            ${escapeHtml(meta.document_date || doc.created_at.split('T')[0])}
          </td>

          <td class="supplied-8def568bda">
            <button class="btn btn-secondary btn-sm btn-inspect-doc" data-doc-id="${doc.id}" ${doc.status!=='ready'?'disabled':''}>
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
            <div class="supplied-a609928111">
              <h3 class="supplied-6fdd6821ed">Upload document</h3>
            </div>
            <button class="drawer-close" id="btn-close-modal">&times;</button>
          </div>

          <div class="modal-body" id="modal-wizard-body">
            <!-- Step 1: File Selection -->
            <div id="upload-step-1">
              <div class="upload-dropzone" id="dropzone-area">
                <div class="upload-icon supplied-7d9b07efad">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><polyline points="17 14 12 9 7 14"/><line x1="12" y1="9" x2="12" y2="20"/></svg>
                </div>
                <div class="supplied-bb884e2684">
                  Drag & Drop legal file here, or click to browse
                </div>
                <div class="supplied-2f79e19d33">
                  PDF, DOCX, TXT, images · max 25 MB. Legacy DOC requires server support.
                </div>
                <input type="file" id="file-picker-input" accept=".pdf,.docx,.txt,.doc,.png,.jpg,.jpeg,.tif,.tiff" / class="supplied-6e22c58a7a">
              </div>

              <div id="selected-file-info" class="supplied-e82130e41c">
                <div id="selected-file-name" class="supplied-8130917365">filename.pdf</div>
                <div id="selected-file-meta" class="supplied-bb958524c9">
                  Size: 2.4 MB | SHA256: calculating...
                </div>
              </div>

              <!-- Metadata Form Fields -->
              <details class="simple-options"><summary>Document details (optional)</summary><div class="supplied-b1f256fafc">
                <div>
                  <label class="supplied-9337b8fbdf">Document Title</label>
                  <input type="text" class="input" id="upload-meta-title" placeholder="e.g. Non-Disclosure Agreement" />
                </div>
                <div>
                  <label class="supplied-9337b8fbdf">Document Type</label>
                  <select class="select" id="upload-meta-type">
                    <option value="contract">Commercial Contract</option>
                    <option value="judgment">Court Judgment / Precedent</option>
                    <option value="statute">Statute / Regulation</option>
                    <option value="annexure">Annexure / Schedule</option>
                    <option value="sow">Statement of Work</option>
                  </select>
                </div>
                <div>
                  <label class="supplied-9337b8fbdf">Jurisdiction</label>
                  <select class="select" id="upload-meta-jurisdiction">
                    <option value="IN">India</option>
                    <option value="IN-MH">India - Maharashtra (IN-MH)</option>
                    <option value="US-DE">United States - Delaware (US-DE)</option>
                    <option value="UK">United Kingdom (UK)</option>
                  </select>
                </div>
                <div>
                  <label class="supplied-9337b8fbdf">Document Date</label>
                  <input type="text" class="input" id="upload-meta-court" placeholder="Court / authority, if applicable"><input type="date" class="input" id="upload-meta-date"  />
                </div>
              </div></details>
            </div>

            <!-- Step 2: Upload & Indexing Progress -->
            <div id="upload-step-2" class="supplied-f53458721c">
              <div class="supplied-64a0232d3f"></div>
              <h4 id="upload-progress-title" class="supplied-5c77fbc64c">Uploading your document…</h4>
              <p id="upload-progress-desc" class="supplied-97dc74091f">
                Reading your file. It will be ready to use when processing finishes.
              </p>
            </div>
          </div>

          <div class="modal-footer" id="modal-footer-btns">
            <button class="btn btn-ghost" id="btn-cancel-modal">Cancel</button>
            <button class="btn btn-primary" id="btn-submit-upload" disabled>Upload</button>
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

    dropzone.addEventListener('click', e => {if(e.target!==filePicker)filePicker.click();});
    dropzone.addEventListener('dragover', e=>e.preventDefault());
    dropzone.addEventListener('drop', e=>{e.preventDefault();if(e.dataTransfer.files.length){filePicker.files=e.dataTransfer.files;filePicker.dispatchEvent(new Event('change',{bubbles:true}));}});
    filePicker.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        selectedFile = e.target.files[0];
        fileInfoBox.style.display = 'block';
        fileNameEl.textContent = selectedFile.name;
        titleInput.value = selectedFile.name.replace(/\.[^/.]+$/, "");
        
        fileMetaEl.textContent = `Size: ${(selectedFile.size / 1024).toFixed(1)} KB`;
        btnSubmit.disabled = false;
      }
    });

    // Close buttons
    modalContainer.querySelector('#btn-close-modal')?.addEventListener('click', () => { modalContainer.innerHTML = ''; });
    modalContainer.querySelector('#btn-cancel-modal')?.addEventListener('click', () => { modalContainer.innerHTML = ''; });

    // Submit handler (Contract 2.5)
    btnSubmit.addEventListener('click', async () => {
      if (!selectedFile || btnSubmit.disabled) return;
      btnSubmit.disabled=true;

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

        window.showToast("Document parsed and ready", "success");
        setTimeout(async () => {
          modalContainer.innerHTML = '';
          await this.render();
        }, 800);

      } catch (err) {
        console.error(err);
        modalContainer.querySelector('#upload-progress-title').textContent = "Upload Error";
        modalContainer.querySelector('#upload-progress-desc').textContent = err.message || err.error?.message || "Failed to process document upload.";
        step1.style.display='block';footerBtns.style.display='flex';btnSubmit.disabled=false;btnSubmit.textContent='Retry Upload';
      }
    });
  }
}
