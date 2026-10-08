import {LegalApiClient,request} from '../api/api-client.js';
class GlobalCitationDrawer{
  constructor(){
    this.backdrop=document.createElement('div');this.backdrop.className='drawer-backdrop';this.backdrop.onclick=()=>this.close();
    this.drawer=document.createElement('div');this.drawer.className='citation-drawer';this.drawer.setAttribute('aria-hidden','true');this.drawer.inert=true;this.drawer.setAttribute('role','dialog');this.drawer.setAttribute('aria-label','Source inspection');
    this.drawer.innerHTML='<div class="drawer-header"><h3>Source Inspection</h3><button class="drawer-close" aria-label="Close source drawer">×</button></div><div class="drawer-body"></div>';
    this.drawer.querySelector('button').onclick=()=>this.close();document.body.append(this.backdrop,this.drawer);
    document.addEventListener('click',e=>{const target=e.target.closest('.citation-badge,[data-citation-id]');if(!target)return;e.preventDefault();const id=target.dataset.citationId;if(id)this.open(id);else window.showToast?.('This citation has no stored source reference.','error');});
    document.addEventListener('keydown',e=>{if(e.key==='Escape')this.close();});this.sequence=0;
  }
  async open(id){
    const sequence=++this.sequence;this.drawer.setAttribute('aria-hidden','false');this.drawer.inert=false;this.backdrop.classList.add('open');this.drawer.classList.add('open');const body=this.drawer.querySelector('.drawer-body');body.textContent='Loading stored source…';
    try{const cit=(await LegalApiClient.getCitation(id)).data;const chunk=(await LegalApiClient.getChunk(cit.document_id,cit.chunk_id)).data;if(sequence!==this.sequence)return;
      this.currentChunk=chunk;this.currentCitation=cit;body.replaceChildren();
      const append=(tag,text)=>{const el=document.createElement(tag);el.textContent=text;body.append(el);return el;};
      append('h3',cit.document_name||'Source');append('p',`Page: ${cit.page??'unavailable'} · Section: ${cit.section||'unavailable'} · Offsets: ${cit.start_offset??chunk.start_offset}–${cit.end_offset??chunk.end_offset}`);
      if(cit.source_url){
        try{const url=new URL(cit.source_url);if(url.protocol==='https:'){
          const link=append('a','Open source website');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';
        }}catch{}
      }
      if(cit.retrieved_at)append('p','Imported: '+cit.retrieved_at);
      if(cit.snapshot_date)append('p','Dated official snapshot: '+cit.snapshot_date+' · live website was unavailable.');
      if(cit.source_sha256)append('p','Source SHA-256: '+cit.source_sha256);
      append('h4','Exact source quote');const quote=append('blockquote',cit.quoted_text);quote.style.whiteSpace='pre-wrap';
      append('h4','Surrounding context');const context=append('pre',chunk.surrounding_context||chunk.text);context.style.whiteSpace='pre-wrap';context.style.overflowWrap='anywhere';
      append('p','An exact quote verifies the source span; it does not independently establish the truth or legal interpretation.');
      const button=append('button','Download Original');button.className='btn btn-primary';button.onclick=async()=>{try{await LegalApiClient.downloadOriginal(cit.document_id);}catch(e){window.showToast?.(e.message,'error');}};
      if(cit.library_inspection){
        append('h4','Browse extracted passages');let cursor=null;
        const passages=append('div','');const more=append('button','Load passages');more.className='btn btn-secondary';
        more.onclick=async()=>{more.disabled=true;try{
          const params=new URLSearchParams({limit:'20'});if(cursor)params.set('cursor',cursor);
          const data=(await request(`documents/${cit.document_id}/chunks?${params}`)).data;
          if(sequence!==this.sequence)return;
          for(const item of data.items){const section=document.createElement('details');const title=document.createElement('summary');title.textContent=`Page ${item.page??'unavailable'} · ${item.section||'Passage'} · ${item.start_offset}–${item.end_offset}`;const text=document.createElement('pre');text.textContent=item.text;text.style.whiteSpace='pre-wrap';text.style.overflowWrap='anywhere';section.append(title,text);passages.append(section);}
          cursor=data.next_cursor;more.textContent=cursor?'Load more passages':'All passages loaded';more.disabled=!cursor;
        }catch(e){window.showToast?.(e.message,'error');more.disabled=false;}};
      }
    }catch(e){if(sequence===this.sequence)body.textContent=e.message||'Source unavailable.';}
  }
  openDocumentViewer(chunk,cit){return this.open(cit?.id||chunk.document_id);}
  close(){this.sequence++;this.drawer.setAttribute('aria-hidden','true');this.drawer.inert=true;this.backdrop.classList.remove('open');this.drawer.classList.remove('open');}
}
export const CitationDrawer=new GlobalCitationDrawer();
