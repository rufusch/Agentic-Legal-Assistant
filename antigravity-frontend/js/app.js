/* ==========================================================================
   APP MAIN CONTROLLER
   Router, Navigation state, View initialization and Toast manager
   ========================================================================== */

import { LegalApiClient, initializeSession, escapeHtml } from './api/api-client.js';
import { HomepageView } from './views/homepage.js';
import { DocumentsHubView } from './views/documents-hub.js';
import { WorkflowPlaceholderView } from './views/workflow-placeholder.js';
import { ReviewView } from './views/review.js';
import { DraftingView } from './views/drafting.js';

import { ResearchView } from './views/research.js';
import { CitationDrawer } from './components/citation-drawer.js';
import { Icons } from './components/icons.js';

// Global Toast helper
window.showToast = function(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  const icon = type === 'success' ? Icons.check('', 16) : type === 'error' ? Icons.close('', 16) : Icons.sparkles('', 16);
  toast.innerHTML = `<span style="display: flex; align-items: center;">${icon}</span> <span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
};

class App {
  constructor() {
    this.currentView = 'homepage';
    this.views = {};
    this.init().catch(error=>window.showToast(error.message,'error'));
  }

  async init() {
    await initializeSession();
    const home=(await LegalApiClient.home()).data;
    sessionStorage.setItem('caselens.tenant',home.tenant.id);
    const tenant=document.querySelector('.tenant-pill');tenant.title='Authenticated tenant: '+home.tenant.id;tenant.querySelector('span:last-child').textContent='Tenant: '+home.tenant.display_name;
    document.querySelector('.user-name').textContent=home.user.display_name;
    document.querySelector('.user-avatar').textContent=home.user.display_name.slice(0,2).toUpperCase();
    const bell=document.querySelector('[title="Notifications"]');bell.querySelector('.header-icon-badge').textContent=home.notifications.length;
    bell.onclick=()=>window.showToast(home.notifications.slice(0,4).map(n=>n.message).join(' · ')||'No notifications.');
    const search=document.querySelector('.header-search-input');search.addEventListener('keydown',e=>{if(e.key==='Enter'){this.navigateTo('documents').then(()=>{const field=document.querySelector('#input-search-docs');if(field){field.value=search.value;field.dispatchEvent(new Event('input',{bubbles:true}));}});}});
    // 1. Initialize Views
    const homeEl = document.getElementById('view-homepage');
    const docsEl = document.getElementById('view-documents');
    const wf1El = document.getElementById('view-workflow-1');
    const wf2El = document.getElementById('view-workflow-2');
    const wf3El = document.getElementById('view-workflow-3');
    const wf4El = document.getElementById('view-workflow-4');
    const noveltyEl = document.getElementById('view-novelty');

    this.views['homepage'] = new HomepageView(homeEl, (target) => this.navigateTo(target));
    this.views['documents'] = new DocumentsHubView(docsEl);

    // Milestones 2-6 Placeholders
    this.views['workflow-1'] = new ReviewView(wf1El, (target) => this.navigateTo(target));

    this.views['workflow-2'] = new DraftingView(wf2El, (target) => this.navigateTo(target));

    this.views['workflow-3'] = new ResearchView(wf3El, (target) => this.navigateTo(target));

    const planned=(el,name)=>({render:()=>{el.innerHTML='<div class="view-header"><h1>'+name+'</h1></div><section class="card"><h3>Coming in the next development part</h3><p>This workflow is not connected yet. You can use Contract / Case Review, Document Drafting and Legal Research.</p></section>';}});
    this.views['workflow-4']=planned(wf4El,'RAG Chat');
    this.views['novelty']=planned(noveltyEl,'Clause Auditor');



    // 2. Setup Navigation Listeners
    this._bindNavigation();
    document.querySelector('.agent-start-btn')?.addEventListener('click',()=>this.navigateTo('novelty'));

    // 3. Render Initial View
    const hash = window.location.hash.replace('#', '') || 'homepage';
    this.navigateTo(hash);

    // 4. Update Document Badge Count
    this.updateDocBadgeCount();
  }

  _bindNavigation() {
    document.querySelectorAll('.nav-item-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const targetView = btn.getAttribute('data-view');
        this.navigateTo(targetView);
      });
    });

    window.addEventListener('hashchange', () => {
      const hash = window.location.hash.replace('#', '');
      if (hash && hash !== this.currentView) {
        this.navigateTo(hash);
      }
    });
  }

  async navigateTo(viewName) {
    if (!this.views[viewName]) {
      viewName = 'homepage';
    }

    this.currentView = viewName;
    window.location.hash = viewName;

    // Update active nav button
    document.querySelectorAll('.nav-item-btn').forEach(btn => {
      if (btn.getAttribute('data-view') === viewName) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    // Hide all view panels
    document.querySelectorAll('.view-panel').forEach(panel => {
      panel.classList.remove('active');
    });

    // Show target view panel
    const targetPanel = document.getElementById(`view-${viewName}`);
    if (targetPanel) {
      targetPanel.classList.add('active');
      // Render view
      if (this.views[viewName].render) {
        await this.views[viewName].render();
      }
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async updateDocBadgeCount() {
    try {
      const docsRes = await LegalApiClient.listDocuments();
      const countEl = document.getElementById('nav-badge-docs-count');
      if (countEl) {
        countEl.textContent = docsRes.data.length;
      }
    } catch (e) {
      console.warn("Could not update badge count:", e);
    }
  }
}

// Start application on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
  window.app = new App();
});
