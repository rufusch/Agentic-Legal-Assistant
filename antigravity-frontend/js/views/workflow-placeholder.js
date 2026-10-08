/* ==========================================================================
   WORKFLOW PLACEHOLDER VIEW
   Displays planned endpoints and requirements for subsequent workflow milestones
   ========================================================================== */

export class WorkflowPlaceholderView {
  constructor(containerEl, workflowInfo) {
    this.container = containerEl;
    this.info = workflowInfo;
  }

  render() {
    this.container.innerHTML = `
      <div class="view-header">
        <div class="view-title-group">
          <div style="display: flex; align-items: center; gap: 0.65rem; margin-bottom: 0.25rem;">
            <h1>${this.info.title}</h1>
            <span class="badge ${this.info.badgeClass || 'badge-processing'}">${this.info.badgeText}</span>
          </div>
          <p class="view-subtitle">${this.info.description}</p>
        </div>
      </div>

      <div class="card" style="margin-bottom: 2rem;">
        <div style="display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem;">
          <span style="font-size: 2.5rem;">${this.info.icon}</span>
          <div>
            <h3 style="font-size: 1.2rem; margin-bottom: 0.2rem;">${this.info.title} — Part ${this.info.partNumber}</h3>
            <p style="font-size: 0.85rem; color: var(--text-muted);">
              Contract Reference: <strong>${this.info.contractSection}</strong> | Endpoints: <code style="color: var(--burgundy-accent); font-weight: 600;">${this.info.endpoints}</code>
            </p>
          </div>
        </div>

        <div style="background: #FDF9F2; border: 1px solid #EFE4D2; border-radius: var(--radius-md); padding: 1.25rem; margin-bottom: 1.5rem;">
          <div style="font-size: 0.78rem; text-transform: uppercase; font-weight: 700; color: var(--burgundy-accent); letter-spacing: 0.05em; margin-bottom: 0.75rem;">
            Key Capabilities Scheduled in Milestone Part ${this.info.partNumber}
          </div>
          <ul style="list-style-type: disc; padding-left: 1.5rem; color: var(--text-secondary); font-size: 0.9rem; line-height: 1.7;">
            ${this.info.features.map(f => `<li>${f}</li>`).join('')}
          </ul>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 1rem; border-top: 1px solid var(--border-subtle);">
          <span style="font-size: 0.8rem; color: var(--text-dim);">
            Foundation: All shared documents, citation drawer [S1], and SSE job pipeline are already built in Part 1.
          </span>
          <button class="btn btn-secondary btn-sm" onclick="window.location.hash='#homepage'">
            &larr; Back to Dashboard
          </button>
        </div>
      </div>
    `;
  }
}
