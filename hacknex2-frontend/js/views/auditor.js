import {request,escapeHtml,registerEvidence,download} from '../api/api-client.js';
import {renderCitationBadge} from '../components/shared-ui.js';

export class AuditorView {
  constructor(el){this.el=el;}
  async render(){
    const rows=(await request('grounding-audit/outputs')).data.items;
    this.el.innerHTML=`<div class="view-header"><div class="view-eyebrow">EVIDENCE VERIFICATION</div><h1>Clause Auditor</h1><p>Inspect the source trail of a completed review, draft, research memo or chat answer.</p></div>
      <section class="card rv-card"><h3>Choose a completed output</h3><select class="input" id="audit-output" aria-label="Completed output">${rows.map((r,i)=>`<option value="${i}">${escapeHtml(r.workflow+' · '+r.title+' · '+r.claim_count+' claims')}</option>`).join('')}</select><button class="btn btn-primary" id="audit-run" ${rows.length?'':'disabled'}>Check source integrity</button><p>Exact quotes and offsets are checked in code. This is not a certificate of legal correctness.</p></section><div id="audit-result" aria-live="polite"></div>`;
    this.el.querySelector('#audit-run').onclick=async()=>{
      const button=this.el.querySelector('#audit-run');button.disabled=true;
      try{
        const row=rows[Number(this.el.querySelector('#audit-output').value)];
        const query=new URLSearchParams({workflow:row.workflow,resource_id:row.id});
        const audit=(await request('grounding-audit?'+query)).data;registerEvidence(audit);
        const target=this.el.querySelector('#audit-result');
        target.innerHTML=`<section class="card rv-card"><h2>${audit.abstained?'No substantive claims to audit':audit.source_integrity_passed?'Source integrity checks passed':'Review needed'}</h2><p>${audit.traceable_claims} of ${audit.claim_count} claims resolve to stored sources. ${audit.traceability_score===null?'No score for an empty answer.':'Quote traceability: '+Math.round(audit.traceability_score*100)+'%.'}</p>${audit.pending_edit_verification?'<p>Draft edits still require verification.</p>':''}<button class="btn btn-secondary" id="audit-export">Export audit JSON</button></section>
        ${audit.claims.map(c=>`<section class="card rv-card"><p>${escapeHtml(c.text)}</p><p>${c.source_integrity?'Exact source found':'Missing or invalid source'} · ${c.material_values_present?'Numeric values present in sources':'Numeric value mismatch'}</p>${c.citation_ids.map(id=>{const ref=audit.citations.find(c=>c.id===id);return ref?renderCitationBadge(ref.label,ref.id):'';}).join('')}<p>Support status: ${escapeHtml(c.support_status)}. Human review required.</p></section>`).join('')}
        <section class="card rv-card"><h3>Scope and limitations</h3>${audit.limitations.map(l=>`<p>${escapeHtml(l)}</p>`).join('')}</section>`;
        target.querySelector('#audit-export').onclick=()=>download('grounding-audit/export?'+query,'grounding-audit.json');
      }catch(e){window.showToast?.(e.message,'error');}finally{button.disabled=false;}
    };
  }
}
