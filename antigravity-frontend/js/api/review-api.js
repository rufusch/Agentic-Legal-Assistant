import {request,generateUUID,registerEvidence,download} from './api-client.js';
async function resolve(id,version){if(!version)return id;const versions=(await request(`reviews/${id}/versions`)).data.items;const report=versions.find(v=>v.version===Number(version));if(!report)throw new Error('Review version unavailable.');return report.id;}
export const ReviewApi={
  createReview:(body,key=generateUUID())=>request('reviews',{method:'POST',body,idempotencyKey:key}),
  async getReview(id,version){const res=await request('reviews/'+await resolve(id,version));registerEvidence(res.data);return res;},
  rerunReview:(id,body)=>request(`reviews/${id}/rerun`,{method:'POST',body,idempotencyKey:generateUUID()}),
  async listVersions(id){const res=await request(`reviews/${id}/versions`);return {data:res.data.items};},
  async exportReview(id,format,version){return download(`reviews/${await resolve(id,version)}/export?format=${format}`,`review-v${version}.${format}`);}
};
