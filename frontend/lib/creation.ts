import {api} from "@/lib/api";
import {saveEntry,updateEntry} from "@/lib/library";
import type {CreationRequest,LibraryEntry} from "@/lib/library";

export async function beginCreation(request:CreationRequest,existing?:LibraryEntry):Promise<LibraryEntry> {
  if (existing?.createKey && existing.createRequest &&
      (existing.createRequest.setting!==request.setting || existing.createRequest.era!==request.era)) {
    throw new Error('未确认的创建请求必须先恢复，不能修改原请求后重复提交。');
  }
  const entry=saveEntry({...existing,id:existing?.id||crypto.randomUUID(),token:existing?.token||
    (crypto.randomUUID()+crypto.randomUUID()).replaceAll('-',''),kind:'custom',title:existing?.title||'准备新故事',
    provider:'deepseek',modelId:existing?.modelId||'deepseek-flash',draft:existing?.draft||'',
    createRequest:existing?.createRequest||request,createKey:existing?.createKey||crypto.randomUUID(),updatedAt:new Date().toISOString()});
  const session=await api.createCustomSession(entry.token);
  updateEntry(entry.id,{sessionId:session.session_id,provider:session.provider,modelId:session.model_id});
  const task=await api.createTask(entry.token,entry.createRequest!,entry.createKey!);
  return updateEntry(entry.id,{creationTaskId:task.task_id});
}

export async function resumeCreation(entry:LibraryEntry):Promise<LibraryEntry> {
  const key=entry.creationResumeKey||crypto.randomUUID();
  updateEntry(entry.id,{creationResumeKey:key});
  const result=await api.resumeCreation(entry.token,entry.creationTaskId!,key);
  return updateEntry(entry.id,{creationTaskId:result.task_id,creationResumeKey:undefined});
}

export async function prepareImages(entry:LibraryEntry,confirmMissingOutput=false):Promise<LibraryEntry> {
  if (entry.imageTaskId) {
    const key=entry.imageResumeKey||crypto.randomUUID();
    updateEntry(entry.id,{imageResumeKey:key});
    const task=await api.resumeImages(entry.token,entry.imageTaskId,key,confirmMissingOutput);
    return updateEntry(entry.id,{imageTaskId:task.task_id,imageResumeKey:undefined});
  }
  const key=entry.imageKey||crypto.randomUUID();updateEntry(entry.id,{imageKey:key});
  const task=await api.startImages(entry.token,key);
  return updateEntry(entry.id,{imageTaskId:task.task_id});
}
