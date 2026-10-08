import { escapeHtml } from '../api/api-client.js';

export function officialSourceLinks(citations = []) {
  const seen = new Set();
  const links = [];
  for (const citation of citations) {
    try {
      const url = new URL(citation.source_url);
      if (url.protocol !== 'https:' || seen.has(url.href)) continue;
      seen.add(url.href);
      const date = citation.snapshot_date ? ` · dated snapshot ${citation.snapshot_date}` : '';
      links.push(`<li><a href="${escapeHtml(url.href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(citation.document_name || url.hostname)}</a>${escapeHtml(date)}<br><small>${escapeHtml(url.href)}</small></li>`);
    } catch {}
  }
  return links.length ? `<section class="card rv-card"><h3>Official source links</h3><ul>${links.join('')}</ul></section>` : '';
}
