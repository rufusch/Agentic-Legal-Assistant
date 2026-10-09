import assert from 'node:assert/strict';
globalThis.window = { showToast() {} };
globalThis.location = { origin: 'http://localhost' };
const { ReviewView } = await import('../js/views/review.js');
const { LegalApiClient } = await import('../js/api/api-client.js');
function element() {
  return { value: '', style: {}, children: [], handlers: {}, classList: { toggle() {} },
    addEventListener(name, fn) { this.handlers[name] = fn; },
    append(child) { this.children.push(child); }, setAttribute() {}, click() { this.clicks = (this.clicks || 0) + 1; } };
}
globalThis.document = { createElement: element };
const nodes = new Map();
const get = selector => { if (!nodes.has(selector)) nodes.set(selector, element()); return nodes.get(selector); };
const view = Object.create(ReviewView.prototype);
Object.assign(view, { el: { querySelector: get, querySelectorAll: () => [] },
  docs: [], form: { document_ids: [], options: {}, focus_question: '' }, fieldErrors: {},
  _saveDraft() {}, _docRows() { return 'updated'; },
  _renderSetup() { throw new Error('Upload must not replace the form'); } });
view._bindSetup();
const input = get('#rv-file-upload'), box = get('#rv-upload-box');
box.handlers.click({ target: input });
assert.equal(input.clicks, undefined);
box.handlers.click({ target: box });
assert.equal(input.clicks, 1);
let finish;
LegalApiClient.uploadDocument = async (file, metadata, onUploaded) => {
  onUploaded({ job_id: 'job' });
  return await new Promise(resolve => { finish = resolve; });
};
const upload = input.handlers.change({ target: { files: [{ name: 'contract.pdf' }] } });
assert.notEqual(box.style.pointerEvents, 'none');
assert.match(get('#rv-upload-status').children[0].textContent, /Reading and indexing/);
view.form.focus_question = 'An edit made during parsing';
finish({ data: { id: 'doc', status: 'ready' } });
await upload;
assert.equal(view.form.focus_question, 'An edit made during parsing');
assert.deepEqual(view.form.document_ids, ['doc']);
LegalApiClient.uploadDocument = async () => { throw new Error('Upload integrity error'); };
await input.handlers.change({ target: { files: [{ name: 'contract.pdf' }] } });
assert.equal(get('#rv-upload-status').children.at(-1).textContent, 'Upload integrity error');
assert.notEqual(box.style.pointerEvents, 'none');
console.log('Upload keeps inputs usable, preserves edits, selects ready files and reports errors.');
