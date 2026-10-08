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
          <div class="supplied-29ced55988">
            <h1>${this.info.title}</h1>
            <span class="badge ${this.info.badgeClass || 'badge-processing'}">${this.info.badgeText}</span>
          </div>
          <p class="view-subtitle">${this.info.description}</p>
        </div>
      </div>

      <div class="card supplied-1cd896a576">
        <div class="supplied-6c6484dbef">
          <span class="supplied-b3b25bb768">${this.info.icon}</span>
          <div>
            <h3 class="supplied-84020b645b">${this.info.title} — Part ${this.info.partNumber}</h3>
            <p class="supplied-97dc74091f">
              Contract Reference: <strong>${this.info.contractSection}</strong> | Endpoints: <code class="supplied-787a453ebf">${this.info.endpoints}</code>
            </p>
          </div>
        </div>

        <div class="supplied-fb6f5b89f8">
          <div class="supplied-261afc2559">
            Key Capabilities Scheduled in Milestone Part ${this.info.partNumber}
          </div>
          <ul class="supplied-fc4ca1a065">
            ${this.info.features.map(f => `<li>${f}</li>`).join('')}
          </ul>
        </div>

        <div class="supplied-f6d215ffb2">
          <span class="supplied-2f79e19d33">
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
