/* ==========================================================================
   HOMEPAGE VIEW
   Official, clean executive design without emojis
   Features: Hero Banner, 4 Feature Cards, Recent Activity, AI Assistant, Quick Access
   ========================================================================== */

import { LegalApiClient, escapeHtml } from '../api/api-client.js';
import { Icons } from '../components/icons.js';

export class HomepageView {
  constructor(containerEl, onNavigate) {
    this.container = containerEl;
    this.onNavigate = onNavigate;
  }

  async render() {
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
          <button class="btn btn-gold" id="btn-hero-new-query">
            <span>Start a New Query</span>
            ${Icons.arrowRight('', 16)}
          </button>
        </div>

        <!-- Center Classical Scales Emblem -->
        <div class="hero-sculpture-wrap">
          <div style="color: var(--accent-gold); opacity: 0.85;">
            ${Icons.scales('', 120)}
          </div>
        </div>

        <!-- Right Feature Quick Pills -->
        <div class="hero-feature-pills">
          <div class="hero-pill-item" id="pill-understand-docs" style="cursor: pointer;">
            <span class="hero-pill-icon">${Icons.fileText('', 16)}</span>
            <span>Understand legal documents</span>
          </div>
          <div class="hero-pill-item" id="pill-find-cases" style="cursor: pointer;">
            <span class="hero-pill-icon">${Icons.search('', 16)}</span>
            <span>Find relevant case laws</span>
          </div>
          <div class="hero-pill-item" id="pill-draft-docs" style="cursor: pointer;">
            <span class="hero-pill-icon">${Icons.edit('', 16)}</span>
            <span>Draft accurate legal documents</span>
          </div>
          <div class="hero-pill-item" id="pill-ai-agent" style="cursor: pointer;">
            <span class="hero-pill-icon">${Icons.bot('', 16)}</span>
            <span>Work with your AI agent</span>
          </div>
        </div>
      </div>

      <!-- 2. 4-COLUMN FEATURE CARDS -->
      <div class="feature-cards-grid">
        <!-- Card 1: Document Analysis -->
        <div class="feature-box" id="card-feature-review">
          <div>
            <div class="feature-box-icon">${Icons.fileText('', 22)}</div>
            <h3 class="feature-box-title">Contract / Case Review</h3>
            <p class="feature-box-desc">
              Upload and get instant insights, key clauses, risks and summaries.
            </p>
          </div>
          <div class="feature-box-action">
            <span>Analyze Document</span>
            ${Icons.arrowRight('', 15)}
          </div>
        </div>

        <!-- Card 2: Legal Research -->
        <div class="feature-box" id="card-feature-research">
          <div>
            <div class="feature-box-icon">${Icons.search('', 22)}</div>
            <h3 class="feature-box-title">Legal Research</h3>
            <p class="feature-box-desc">
              Research uploaded case laws, statutes and legal precedents with source references.
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
            <h3 class="feature-box-title">Document Drafting</h3>
            <p class="feature-box-desc">
              Generate contracts, notices, pleadings and more with AI.
            </p>
          </div>
          <div class="feature-box-action">
            <span>Create Document</span>
            ${Icons.arrowRight('', 15)}
          </div>
        </div>

        <!-- Card 4: Autonomous Agent -->
        <div class="feature-box" id="card-feature-agent">
          <div>
            <div class="feature-box-icon">${Icons.bot('', 22)}</div>
            <h3 class="feature-box-title">Autonomous Agent</h3>
            <p class="feature-box-desc">
              Let the AI agent handle multi-step tasks for you.
            </p>
          </div>
          <div class="feature-box-action">
            <span>Activate Agent</span>
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

          <div class="activity-list" id="live-activity"></div>
        </div>

        <!-- Center: AI Legal Assistant Chat Panel -->
        <div class="assistant-panel">
          <div>
            <div class="assistant-header">
              <div class="assistant-profile">
                <div class="assistant-avatar">${Icons.scales('', 18)}</div>
                <div>
                  <div class="assistant-name">AI Legal Assistant</div>
                  <span class="assistant-status-dot">Planned</span>
                </div>
              </div>
              <div style="display: flex; gap: 0.65rem; color: var(--text-muted);">
                <button class="btn btn-ghost btn-sm" style="padding: 0.2rem 0.4rem;" title="Query History">${Icons.clock('', 16)}</button>
                <button class="btn btn-ghost btn-sm" style="padding: 0.2rem 0.4rem;" title="Assistant Settings">${Icons.settings('', 16)}</button>
              </div>
            </div>

            <!-- Welcome Bubble -->
            <div class="assistant-welcome-bubble">
              <div style="display: flex; align-items: center; gap: 0.35rem; color: var(--accent-gold); font-size: 0.82rem; font-weight: 700; margin-bottom: 0.35rem;">
                ${Icons.sparkles('', 14)}
                <span>Welcome to your legal workspace</span>
              </div>
              <div class="assistant-welcome-text">
                Review documents, prepare drafts, or research uploaded authorities. RAG Chat is coming next.
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
            <span style="color: var(--text-muted); cursor: pointer; display: flex; align-items: center;" title="Attach Document">
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
            <div style="font-size: 0.95rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.85rem;">
              Quick Access
            </div>
            <ul class="quick-access-list">
              <li class="quick-access-link" onclick="window.app.navigateTo('workflow-3')">
                <span style="display: flex; align-items: center; gap: 0.6rem;">
                  <span>${Icons.book('', 16)}</span> <span>Indian Penal Code</span>
                </span>
                <span style="color: var(--text-muted);">${Icons.chevronRight('', 14)}</span>
              </li>
              <li class="quick-access-link" onclick="window.app.navigateTo('workflow-3')">
                <span style="display: flex; align-items: center; gap: 0.6rem;">
                  <span>${Icons.scales('', 16)}</span> <span>Constitution of India</span>
                </span>
                <span style="color: var(--text-muted);">${Icons.chevronRight('', 14)}</span>
              </li>
              <li class="quick-access-link" onclick="window.app.navigateTo('documents')">
                <span style="display: flex; align-items: center; gap: 0.6rem;">
                  <span>${Icons.fileText('', 16)}</span> <span>Latest Judgments</span>
                </span>
                <span style="color: var(--text-muted);">${Icons.chevronRight('', 14)}</span>
              </li>
              <li class="quick-access-link" onclick="window.app.navigateTo('workflow-2')">
                <span style="display: flex; align-items: center; gap: 0.6rem;">
                  <span>${Icons.edit('', 16)}</span> <span>Legal Templates</span>
                </span>
                <span style="color: var(--text-muted);">${Icons.chevronRight('', 14)}</span>
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

    const home=(await LegalApiClient.home()).data;
    const activity=this.container.querySelector('#live-activity');
    activity.innerHTML=home.recent_activity.length?home.recent_activity.map(a=>`<div class="activity-item"><div class="activity-icon-wrap">${Icons.fileText('',16)}</div><div class="activity-info"><div class="activity-name">${escapeHtml(a.action.replaceAll('.',' · '))}</div><div class="activity-meta">${escapeHtml(a.resource_id)}</div></div><div class="activity-time">${escapeHtml(new Date(a.timestamp*1000).toLocaleString())}</div></div>`).join(''):'<p style="padding:1rem">No activity yet. Upload a document to begin.</p>';
    this._bindEvents();
  }

  _bindEvents() {
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

    const sendBtn = this.container.querySelector('#btn-assistant-send');
    const inputQ = this.container.querySelector('#input-assistant-query');
    sendBtn?.addEventListener('click', () => {
      if (inputQ && inputQ.value.trim()) {
        window.showToast('RAG Chat is scheduled for the next development part.', 'info');
        setTimeout(() => this.onNavigate('workflow-4'), 600);
      }
    });
    inputQ?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') sendBtn?.click();
    });
  }
}
