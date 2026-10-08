import {request,registerEvidence,generateUUID} from './api-client.js';
export const ChatApi={
 list:()=>request('conversations'),
 config:()=>request('chat/config'),
 createConversation:payload=>request('conversations',{method:'POST',body:payload,idempotencyKey:generateUUID()}),
 getMessages:async id=>{const response=await request(`conversations/${id}/messages`);response.data.forEach(registerEvidence);return response;},
 sendMessage:(id,payload)=>request(`conversations/${id}/messages`,{method:'POST',body:payload,idempotencyKey:generateUUID()}),
 feedback:(cid,mid,payload)=>request(`conversations/${cid}/messages/${mid}/feedback`,{method:'POST',body:payload})
};
