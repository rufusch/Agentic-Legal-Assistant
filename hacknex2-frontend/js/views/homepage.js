/* ==========================================================================
   HOMEPAGE VIEW
   Official, clean executive design without emojis
   Features: Hero Banner, 4 Feature Cards, Recent Activity, AI Assistant, Quick Access
   ========================================================================== */

import { LegalApiClient, escapeHtml, request } from '../api/api-client.js';
import { Icons } from '../components/icons.js';

export class HomepageView {
  constructor(containerEl, onNavigate) {
    this.container = containerEl;
    this.onNavigate = onNavigate;
  }

  async render() {
    const home=(await LegalApiClient.home()).data;
    this.container.innerHTML = `
      <!-- 1. HERO BANNER -->
      <div class="hero-banner">
        <div class="hero-content-left">
          <div class="hero-tagline">YOUR AI LEGAL ASSISTANT</div>
          <h1 class="hero-title">
            Legal Intelligence,<br>
            <em>Automated.</em>
          </h1>
          <p class="hero-subtitle">Analyze. Research. Draft. Decide.</p>
          <button class="btn btn-gold" id="home-upload">
            <span>Upload & summarize</span>
            ${Icons.arrowRight('', 16)}
          </button>
          <button class="btn btn-secondary" id="btn-hero-new-query">Use a saved document</button>
        </div>

        <!-- Center Classical Scales Emblem -->
        <div class="hero-sculpture-wrap">
          <div class="supplied-7aec473298">
            ${Icons.scales('', 120)}
          </div>
        </div>

        <!-- Right Feature Quick Pills -->
        <div class="hero-feature-pills">
          <div class="hero-pill-item supplied-7c0f86ab54" id="pill-understand-docs">
            <span class="hero-pill-icon">${Icons.fileText('', 16)}</span>
            <span>Read and summarize documents</span>
          </div>
          <div class="hero-pill-item supplied-7c0f86ab54" id="pill-find-cases">
            <span class="hero-pill-icon">${Icons.search('', 16)}</span>
            <span>Find relevant case laws</span>
          </div>
          <div class="hero-pill-item supplied-7c0f86ab54" id="pill-draft-docs">
            <span class="hero-pill-icon">${Icons.edit('', 16)}</span>
            <span>Create a legal draft</span>
          </div>
          <div class="hero-pill-item supplied-7c0f86ab54" id="pill-ai-agent">
            <span class="hero-pill-icon">${Icons.bot('', 16)}</span>
            <span>Ask about your documents</span>
          </div>
        </div>
      </div>

      <!-- 2. 4-COLUMN FEATURE CARDS -->
      <div class="feature-cards-grid">
        <!-- Card 1: Read a Document -->
        <div class="feature-box" id="card-feature-review">
          <div>
            <div class="feature-box-icon">${Icons.fileText('', 22)}</div>
            <h3 class="feature-box-title">Read a Document</h3>
            <p class="feature-box-desc">
              Upload a file and receive a plain-language summary with source links.
            </p>
          </div>
          <div class="feature-box-action">
            <span>Read Document</span>
            ${Icons.arrowRight('', 15)}
          </div>
        </div>

        <!-- Card 2: Legal Research -->
        <div class="feature-box" id="card-feature-research">
          <div>
            <div class="feature-box-icon">${Icons.search('', 22)}</div>
            <h3 class="feature-box-title">Legal Research</h3>
            <p class="feature-box-desc">
              Research uploaded case laws, statutes and precedents with source references.
            </p>
          </div>
          <div class="feature-box-action">
            <span>Start Research</span>
            ${Icons.arrowRight('', 15)}
          </div>
        </div>

        <!-- Card 3: Drafting Assistant -->
        <div class="feature-box" id="card-feature-drafting">
          <div>
            <div class="feature-box-icon">${Icons.edit('', 22)}</div>
            <h3 class="feature-box-title">Drafting Assistant</h3>
            <p class="feature-box-desc">
              Generate contracts, notices, pleadings and more with AI.
            </p>
          </div>
          <div class="feature-box-action">
            <span>Create Document</span>
            ${Icons.arrowRight('', 15)}
          </div>
        </div>

        <!-- Card 4: Ask a Question -->
        <div class="feature-box" id="card-feature-agent">
          <div>
            <div class="feature-box-icon">${Icons.bot('', 22)}</div>
            <h3 class="feature-box-title">Ask a Question</h3>
            <p class="feature-box-desc">
              Ask questions about your uploaded documents and get cited answers.
            </p>
          </div>
          <div class="feature-box-action">
            <span>Open Chat</span>
            ${Icons.arrowRight('', 15)}
          </div>
        </div>
      </div>

      <!-- 3. BOTTOM 3-COLUMN DASHBOARD -->
      <div class="dashboard-bottom-grid">
        
        <!-- Left: Recent Activity -->
        <div class="activity-card">
          <div class="section-card-header">
            <h3 class="section-card-title">Recent Activity</h3>
            <span class="section-card-link" id="link-view-all-activity">
              <span>View All</span>
              ${Icons.arrowRight('', 13)}
            </span>
          </div>

          <div class="activity-list">${home.recent_activity.slice(0,4).map(a=>`<div class="activity-item"><div class="activity-icon-wrap">${Icons.fileText("",16)}</div><div class="activity-info"><div class="activity-name">${escapeHtml(a.action.replace("."," · "))}</div><div class="activity-meta">${escapeHtml(a.resource_id)}</div></div><div class="activity-time">${escapeHtml(new Date(a.timestamp*1000).toLocaleString())}</div></div>`).join("") || "<p>No activity yet.</p>"}
          </div>
        </div>

        <!-- Center: AI Legal Assistant Chat Panel -->
        <div class="assistant-panel">
          <div>
            <div class="assistant-header">
              <div class="assistant-profile">
                <div class="assistant-avatar">${Icons.scales('', 18)}</div>
                <div>
                  <div class="assistant-name">AI Legal Assistant</div>
                  <span class="assistant-status-dot">● Connected</span>
                </div>
              </div>
              <div class="supplied-a4fff4ab9e">
                <button class="btn btn-ghost btn-sm supplied-72ad0379fb" title="Query History">${Icons.clock('', 16)}</button>
                <button class="btn btn-ghost btn-sm supplied-72ad0379fb" title="Assistant Settings">${Icons.settings('', 16)}</button>
              </div>
            </div>

            <!-- Welcome Bubble -->
            <div class="assistant-welcome-bubble">
              <div class="supplied-b5c6f42940">
                ${Icons.sparkles('', 14)}
                <span>Welcome to your legal workspace</span>
              </div>
              <div class="assistant-welcome-text">
                I'm your AI legal assistant. How can I help you today?
              </div>
            </div>

            <!-- Suggestion Chips -->
            <div class="assistant-prompt-chips">
              <button class="prompt-chip" data-prompt="Summarize this document">Summarize this document</button>
              <button class="prompt-chip" data-prompt="Find relevant case laws">Find relevant case laws</button>
              <button class="prompt-chip" data-prompt="Draft a legal notice">Draft a legal notice</button>
              <button class="prompt-chip" data-prompt="Explain this clause">Explain this clause</button>
            </div>
          </div>

          <!-- Chat Input -->
          <div class="assistant-chat-input-box">
            <span title="Attach Document" class="supplied-f1fec13f18">
              ${Icons.paperclip('', 16)}
            </span>
            <input type="text" class="assistant-input" id="input-assistant-query" placeholder="Ask a legal question, upload a document, or tell me what you need..." />
            <button class="assistant-btn-send" id="btn-assistant-send" title="Send Query">
              ${Icons.arrowRight('', 14)}
            </button>
          </div>
        </div>

        <!-- Right: Quick Access & Quote -->
        <div class="quick-access-wrap">
          <div class="quick-access-card">
            <div class="supplied-b726b955dc">
              Quick Access
            </div>
            <ul class="quick-access-list">
              <li class="quick-access-link" data-destination="workflow-3">
                <span class="supplied-bae725f7c2">
                  <span>${Icons.book('', 16)}</span> <span>Indian Penal Code</span>
                </span>
                <span class="supplied-9d21da37c4">${Icons.chevronRight('', 14)}</span>
              </li>
              <li class="quick-access-link" data-destination="workflow-3">
                <span class="supplied-bae725f7c2">
                  <span>${Icons.scales('', 16)}</span> <span>Constitution of India</span>
                </span>
                <span class="supplied-9d21da37c4">${Icons.chevronRight('', 14)}</span>
              </li>
              <li class="quick-access-link" data-destination="documents">
                <span class="supplied-bae725f7c2">
                  <span>${Icons.fileText('', 16)}</span> <span>Latest Judgments</span>
                </span>
                <span class="supplied-9d21da37c4">${Icons.chevronRight('', 14)}</span>
              </li>
              <li class="quick-access-link" data-destination="workflow-2">
                <span class="supplied-bae725f7c2">
                  <span>${Icons.edit('', 16)}</span> <span>Legal Templates</span>
                </span>
                <span class="supplied-9d21da37c4">${Icons.chevronRight('', 14)}</span>
              </li>
            </ul>
          </div>

          <!-- Quotation Card -->
          <div class="quote-card">
            <div class="quote-mark">“</div>
            <div class="quote-text">
              The law is not just a set of rules, it's a framework for a better, fairer society.
            </div>
          </div>
        </div>

      </div>
    `;

    this._bindEvents();
  }

  _bindEvents() {
    this.container.querySelector('#home-upload').onclick=async()=>{await this.onNavigate('workflow-1');document.querySelector('#reader-file')?.click();};
    // Hero Actions
    this.container.querySelector('#btn-hero-new-query')?.addEventListener('click', () => this.onNavigate('workflow-1'));
    this.container.querySelector('#pill-understand-docs')?.addEventListener('click', () => this.onNavigate('workflow-1'));
    this.container.querySelector('#pill-find-cases')?.addEventListener('click', () => this.onNavigate('workflow-3'));
    this.container.querySelector('#pill-draft-docs')?.addEventListener('click', () => this.onNavigate('workflow-2'));
    this.container.querySelector('#pill-ai-agent')?.addEventListener('click', () => this.onNavigate('workflow-4'));

    // 4 Feature boxes
    this.container.querySelector('#card-feature-review')?.addEventListener('click', () => this.onNavigate('workflow-1'));
    this.container.querySelector('#card-feature-research')?.addEventListener('click', () => this.onNavigate('workflow-3'));
    this.container.querySelector('#card-feature-drafting')?.addEventListener('click', () => this.onNavigate('workflow-2'));
    this.container.querySelector('#card-feature-agent')?.addEventListener('click', () => this.onNavigate('workflow-4'));

    // Activities
    this.container.querySelector('#link-view-all-activity')?.addEventListener('click', () => this.onNavigate('documents'));
    this.container.querySelector('#act-item-1')?.addEventListener('click', () => this.onNavigate('workflow-1'));
    this.container.querySelector('#act-item-2')?.addEventListener('click', () => this.onNavigate('workflow-3'));
    this.container.querySelector('#act-item-3')?.addEventListener('click', () => this.onNavigate('workflow-2'));
    this.container.querySelector('#act-item-4')?.addEventListener('click', () => this.onNavigate('workflow-4'));

    // Mini assistant chips
    this.container.querySelectorAll('.prompt-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const prompt = chip.getAttribute('data-prompt');
        const input = this.container.querySelector('#input-assistant-query');
        if (input) {
          input.value = prompt;
          input.focus();
        }
      });
    });

    this.container.querySelectorAll('[data-destination]').forEach(link=>link.onclick=()=>this.onNavigate(link.dataset.destination));
    this.container.querySelector('[title="Query History"]').onclick=()=>this.onNavigate('workflow-4');
    this.container.querySelector('[title="Assistant Settings"]').onclick=async()=>{const models=(await request('models')).data;window.showToast(models.filter(m=>m.available).map(m=>m.workflow+': '+m.version).join(' · '));};
    const sendBtn = this.container.querySelector('#btn-assistant-send');
    const inputQ = this.container.querySelector('#input-assistant-query');
    sendBtn?.addEventListener('click', () => {
      if (inputQ && inputQ.value.trim()) {
        sessionStorage.setItem('caselens.chat.prompt',inputQ.value.trim());
        this.onNavigate('workflow-4');
      }
    });
    inputQ?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') sendBtn?.click();
    });
  }
}
