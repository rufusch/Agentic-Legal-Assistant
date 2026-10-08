import {request,generateUUID,registerEvidence,download} from './api-client.js';
export const ResearchApi={
  list:()=>request('research'),
  createResearch(form){const scope=form.jurisdiction.trim();const code=/^IN(?:-[A-Z]{2})?$/.test(scope);const aliases={'Supreme Court':'Supreme Court of India','Delhi High Court':'High Court of Delhi','Bombay High Court':'High Court of Bombay'};return request('research',{method:'POST',idempotencyKey:generateUUID(),body:{question:form.question,context_document_ids:form.document_ids,filters:{jurisdictions:code?[scope]:[],courts:scope&&!code?[aliases[scope]||scope]:[],source_types:['statute','judgment']},options:{include_secondary_sources:false,connect_to_case_facts:true,depth:'deep'}}});},
  async getResearch(id){const res=await request('research/'+id);registerEvidence(res.data);return res;},
  exportResearch:(id,format)=>download(`research/${id}/export?format=${format}`,`legal-research.${format}`)
};
