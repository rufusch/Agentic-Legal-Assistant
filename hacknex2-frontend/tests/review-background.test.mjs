import assert from 'node:assert/strict';

globalThis.window = { showToast() {} };
globalThis.location = { origin: 'http://localhost' };
const { ReviewView } = await import('../js/views/review.js');
const { LegalApiClient } = await import('../js/api/api-client.js');

const view = Object.create(ReviewView.prototype);
Object.assign(view, {
  state: 'setup', form: { focus_question: 'Next audit question' },
  sub: null, report: null, job: null,
  _renderSetup() {}, _isVisible() { return true; },
  _updateAuditStatus() { this.statusUpdated = true; },
  _renderReport() { throw new Error('Completion must not replace edited inputs'); },
  async _loadReport() { this.report = { id: 'report' }; }
});
LegalApiClient.subscribeJobEvents = () => ({ close() {} });
view._startJob('audit');
assert.equal(view.state, 'setup');
assert.ok(view._auditPending());
await view._onEvent({ id: 1, event: 'job.progress', data: { status: 'verifying', progress: .8 } });
assert.equal(view.form.focus_question, 'Next audit question');
await view._onEvent({ id: 2, event: 'job.completed', data: { status: 'completed' } });
assert.equal(view.state, 'setup');
assert.equal(view.form.focus_question, 'Next audit question');
assert.equal(view._auditPending(), false);
assert.ok(view.report);
assert.ok(view.statusUpdated);
console.log('Background audit preserves editable inputs and exposes completed report.');
