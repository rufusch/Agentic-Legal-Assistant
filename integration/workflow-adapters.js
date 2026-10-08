/** Explicit mapping of the supplied CaseLens screens to the v1 API. */
export function createWorkflowAdapters(api) {
  const ids = values => [...new Set(values || [])];
  const courts = { 'Supreme Court': 'Supreme Court of India', 'Delhi High Court': 'High Court of Delhi', 'Bombay High Court': 'High Court of Bombay' };
  return {
    async analyzeRequirements({ documentType, jurisdiction, court, instructions, supportingDocumentIds = [] }) {
      // Select option values should be IN / IN-MH etc., not their rendered labels.
      return api.json('drafts', { method: 'POST', idempotencyKey: crypto.randomUUID(), body: {
        document_type: documentType, jurisdiction: jurisdiction.match(/\bIN(?:-[A-Z]{2})?\b/)?.[0] || jurisdiction, court: courts[court?.trim()] || court?.trim() || null,
        instructions, supporting_document_ids: ids(supportingDocumentIds), facts: {}
      }});
    },
    async runResearch({ question, jurisdictionOrCourt = '', jurisdictionCodes = [], contextDocumentIds = [] }) {
      const scope = jurisdictionOrCourt.trim();
      const isCode = /^IN(?:-[A-Z]{2})?$/.test(scope);
      return api.json('research', { method: 'POST', idempotencyKey: crypto.randomUUID(), body: {
        question, context_document_ids: ids(contextDocumentIds),
        filters: { jurisdictions: ids([...jurisdictionCodes, ...(isCode ? [scope] : [])]), courts: scope && !isCode ? [courts[scope] || scope] : [], source_types: ['statute', 'judgment'] },
        options: { include_secondary_sources: false, connect_to_case_facts: true, depth: 'deep' }
      }});
    },
    requirements: id => api.json(`drafts/${encodeURIComponent(id)}/requirements`),
    saveAnswers: (id, answers) => api.json(`drafts/${encodeURIComponent(id)}/requirements`, { method: 'PATCH', body: { answers } }),
    generateDraft: (id, missingIds = []) => api.json(`drafts/${encodeURIComponent(id)}/generate`, { method: 'POST', idempotencyKey: crypto.randomUUID(), body: { proceed_with_missing_information: missingIds.length > 0, acknowledged_requirement_ids: ids(missingIds) } }),
    research: id => api.json(`research/${encodeURIComponent(id)}`),
    draft: id => api.json(`drafts/${encodeURIComponent(id)}`)
  };
}
