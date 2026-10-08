/** Framework-independent browser client for Antigravity's vanilla JS SPA. */
export class ApiError extends Error {
  constructor(status, error) { super(error.message); this.name = 'ApiError'; this.status = status; Object.assign(this, error); }
}
export function createApiClient({ baseUrl, getToken }) {
  const base = new URL(baseUrl.replace(/\/$/, '') + '/');
  function endpoint(path) {
    const url = new URL(path.startsWith('/api/v1/') ? path : `api/v1/${path.replace(/^\//, '')}`, base);
    if (url.origin !== base.origin || !url.pathname.startsWith('/api/v1/')) throw new Error('Invalid API path');
    return url;
  }
  async function request(path, { method = 'GET', body, raw = false, signal, idempotencyKey, headers: extra = {} } = {}) {
    const headers = new Headers(extra);
    headers.set('Authorization', `Bearer ${await getToken()}`);
    if (body !== undefined && !raw) headers.set('Content-Type', 'application/json');
    if (idempotencyKey) headers.set('Idempotency-Key', idempotencyKey);
    const response = await fetch(endpoint(path), { method, headers, body: body === undefined ? undefined : raw ? body : JSON.stringify(body), signal, credentials: 'omit', redirect: 'error' });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new ApiError(response.status, result.error || { code: 'HTTP_ERROR', message: `Request failed (${response.status})`, field_errors: [] });
    }
    return response;
  }
  async function json(path, options) { const response = await request(path, options); return (await response.json()).data; }
  async function upload(file, metadata = {}, signal) {
    const types = { doc: 'application/msword', pdf: 'application/pdf', docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', txt: 'text/plain', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', tif: 'image/tiff', tiff: 'image/tiff' };
    const content_type = file.type || types[file.name.split('.').pop().toLowerCase()];
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    const sha256 = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
    const ticket = await json('documents/uploads', { method: 'POST', body: { file_name: file.name, content_type, size_bytes: file.size, sha256 }, idempotencyKey: crypto.randomUUID(), signal });
    await request(ticket.upload_url, { method: 'PUT', body: file, raw: true, headers: { 'Content-Type': content_type }, signal });
    return json(`documents/${ticket.document_id}/complete`, { method: 'POST', body: { upload_id: ticket.upload_id, metadata }, idempotencyKey: crypto.randomUUID(), signal });
  }
  // Native EventSource cannot attach bearer headers. Use fetch streaming instead.
  // Persist each returned event.id; reconnect with lastEventId after a disconnect.
  async function* events(jobId, { signal, lastEventId = '0' } = {}) {
    const response = await request(`jobs/${encodeURIComponent(jobId)}/events`, { signal, headers: { Accept: 'text/event-stream', 'Last-Event-ID': lastEventId } });
    const reader = response.body.getReader(), decoder = new TextDecoder(); let pending = '';
    try {
      while (true) {
        const { done, value } = await reader.read();
        pending += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n');
        let boundary;
        while ((boundary = pending.indexOf('\n\n')) !== -1) {
          const frame = pending.slice(0, boundary); pending = pending.slice(boundary + 2);
          let event = 'message', id, data = [];
          for (const line of frame.split('\n')) {
            const colon = line.indexOf(':'); if (colon < 0) continue;
            const key = line.slice(0, colon), value = line.slice(colon + 1).replace(/^ /, '');
            if (key === 'event') event = value; else if (key === 'id') id = value; else if (key === 'data') data.push(value);
          }
          if (data.length) yield { event, id, data: JSON.parse(data.join('\n')) };
        }
        if (done) break;
      }
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  }
  return { json, request, upload, events };
}
