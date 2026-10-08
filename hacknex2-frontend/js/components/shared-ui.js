import {escapeHtml} from '../api/api-client.js';
/* ==========================================================================
   SHARED UI LEGAL PRIMITIVES
   Renders VerifiedClaims, Citations, Warnings, Confidence, and Job Pipelines
   ========================================================================== */

/**
 * Render Citation Badges e.g. [S1]
 */
export function renderCitationBadge(label, citationId = '') {
  return `<button class="citation-badge" data-citation-label="${escapeHtml(label)}" data-citation-id="${escapeHtml(citationId)}" title="Click to inspect verified source chunk">[${escapeHtml(label)}]</button>`;
}

/**
 * Render Confidence Meter
 */
export function renderConfidenceMeter(confidence) {
  if (!confidence) return '';
  const score = confidence.score !== undefined ? Math.round(confidence.score * 100) : 0;
  const level = confidence.level || (score > 80 ? 'high' : score > 50 ? 'medium' : 'low');
  
  return `
    <div class="confidence-meter confidence-${level}" title="${escapeHtml(confidence.explanation || `Confidence: ${score}% (${level})`)}">
      <span class="supplied-4b938c70f5">Confidence:</span>
      <div class="confidence-bar-bg">
        <div class="confidence-bar-fill supplied-width-${Math.round(score)}"></div>
      </div>
      <span class="supplied-3d9df89ef8">${score}%</span>
    </div>
  `;
}

/**
 * Render Warning Callout Box
 * Contract 8.0: "Never hide critical warnings behind a collapsed panel."
 */
export function renderWarningBox(warning, labelFor = (id) => id) {
  const iconMap = {
    info: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    warning: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    critical: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
  };

  return `
    <div class="warning-box ${warning.severity || 'warning'}" id="warning-${warning.id || Math.random().toString(36).substring(7)}">
      <div class="warning-icon">${iconMap[warning.severity] || iconMap.warning}</div>
      <div class="supplied-126244f135">
        <div class="warning-title">${escapeHtml(warning.title)}</div>
        <div class="warning-message">${escapeHtml(warning.message)}</div>
        ${warning.citation_ids && warning.citation_ids.length ? `
          <div class="supplied-d2334c4830">
            <span class="supplied-e2de9432c5">Sources:</span>
            ${warning.citation_ids.map(id => renderCitationBadge(labelFor(id), id)).join('')}
          </div>
        ` : ''}
      </div>
      ${warning.resolvable ? `
        <button class="btn btn-secondary btn-sm supplied-0350e1b239" onclick="window.showToast('Action logged for review', 'info')">
          Resolve
        </button>
      ` : ''}
    </div>
  `;
}

/**
 * Render VerifiedClaim Card
 */
export function renderVerifiedClaim(claim) {
  const statusLabels = {
    supported: 'Supported',
    partially_supported: 'Partially Supported',
    unsupported: 'Unsupported',
    contradicted: 'Contradicted by Evidence'
  };

  const confidenceScore = claim.confidence !== undefined ? Math.round(claim.confidence * 100) : null;

  return `
    <div class="claim-card ${claim.verification_status}">
      <div class="claim-header">
        <span class="claim-status ${claim.verification_status}">
          ${statusLabels[claim.verification_status] || claim.verification_status}
        </span>
        ${confidenceScore !== null ? `
          <span class="supplied-f37f3c622c">
            Score: ${confidenceScore}%
          </span>
        ` : ''}
      </div>
      <div class="claim-text">
        ${escapeHtml(claim.text)}
      </div>
      ${claim.warning ? `
        <div class="supplied-2118bfbebd">
          <span class="supplied-77a3165699">[Notice]</span> <span>${claim.warning}</span>
        </div>
      ` : ''}
      <div class="claim-footer">
        <div class="claim-citations">
          <span class="supplied-f4344b8f4f">Evidence:</span>
          ${(claim.citation_ids || []).map(cid => renderCitationBadge(cid, cid)).join('')}
        </div>
        <span class="supplied-ecab99d36a">ID: ${claim.id.substring(0, 8)}</span>
      </div>
    </div>
  `;
}

/**
 * Render Pipeline Tracker with 8 standard stages
 */
export function renderPipelineTracker(job) {
  const stages = [
    { key: 'queued', label: 'Queued' },
    { key: 'parsing', label: 'Parsing' },
    { key: 'indexing', label: 'Indexing' },
    { key: 'understanding', label: 'Intent & Semantics' },
    { key: 'retrieving', label: 'Retrieval' },
    { key: 'reranking', label: 'Reranking' },
    { key: 'generating', label: 'Generation' },
    { key: 'verifying', label: 'Claim Verification' }
  ];

  const currentStatus = job ? job.status : 'queued';
  const progressPercent = job && job.progress !== undefined ? Math.round(job.progress * 100) : 0;
  
  // Find current active index
  let activeIndex = stages.findIndex(s => s.key === currentStatus);
  if (currentStatus === 'completed' || currentStatus === 'completed_with_warnings') {
    activeIndex = stages.length;
  }

  return `
    <div class="pipeline-tracker" id="pipeline-tracker-root">
      <div class="pipeline-header">
        <div>
          <span class="supplied-2e841a45e8">
            Shared Legal Pipeline Status
          </span>
          <span class="badge ${currentStatus.startsWith('completed') ? 'badge-ready' : 'badge-processing'} supplied-db4dd366ec">
            ${currentStatus.toUpperCase()}
          </span>
        </div>
        <div class="supplied-b2f5304d3f">
          ${progressPercent}% Complete
        </div>
      </div>

      <div class="pipeline-stages">
        ${stages.map((stage, idx) => {
          let stepClass = '';
          if (idx < activeIndex) stepClass = 'done';
          else if (idx === activeIndex) stepClass = 'active';
          return `<div class="stage-step ${stepClass}">${stage.label}</div>`;
        }).join('')}
      </div>

      <div class="progress-bar-container">
        <div class="progress-bar-fill supplied-width-${Math.round(progressPercent)}"></div>
      </div>

      <div class="supplied-a631bf3126">
        <span>${job ? job.message || 'Processing workflow task...' : 'Idle'}</span>
        ${job && job.id ? `<span class="supplied-1d7e6a7c5c">Job: ${job.id.substring(0, 8)}</span>` : ''}
      </div>
    </div>
  `;
}
