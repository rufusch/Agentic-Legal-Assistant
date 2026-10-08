import {request,generateUUID,registerEvidence,download} from './api-client.js';
const envelope=data=>({data});
export const DraftingApi={
  list:()=>request('drafts'),
  createDraft:(body,key=generateUUID())=>request('drafts',{method:'POST',body,idempotencyKey:key}),
  async getRequirements(id){return envelope((await request(`drafts/${id}/requirements`)).data.items);},
  updateRequirements:(id,body)=>request(`drafts/${id}/requirements`,{method:'PATCH',body}),
  generateDraft:(id,body)=>request(`drafts/${id}/generate`,{method:'POST',body,idempotencyKey:generateUUID()}),
  async getDraft(id,version){let d=(await request('drafts/'+id)).data;if(version&&version!==d.version){const versions=(await request(`drafts/${id}/versions`)).data.items;d=versions.find(v=>v.version===Number(version))?.draft;if(!d)throw new Error('Draft version unavailable.');}return envelope(registerEvidence(d));},
  patchSection:(id,section,body)=>request(`drafts/${id}/sections/${section}`,{method:'PATCH',body}),
  verifyDraft:id=>request(`drafts/${id}/verify`,{method:'POST',body:{},idempotencyKey:generateUUID()}),
  async getVersions(id){return envelope((await request(`drafts/${id}/versions`)).data.items.map(v=>({version:v.version,status:v.draft.status,created_at:v.created_at})));},
  async exportDraft(id,format,version){const current=(await request('drafts/'+id)).data;if(version!==current.version)throw new Error('Select the current version before exporting.');return download(`drafts/${id}/export?format=${format}`,`draft-v${version}.${format}`);}
};
