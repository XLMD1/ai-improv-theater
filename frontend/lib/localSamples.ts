import {api} from "@/lib/api";
import {saveEntry,updateEntry} from "@/lib/library";
import type {LibraryEntry} from "@/lib/library";
import type {LocalSample} from './types';

export async function beginLocalSample(sample:Pick<LocalSample,'id'|'title'>,existing?:LibraryEntry):Promise<LibraryEntry> {
  if(existing?.sampleId&&existing.sampleId!==sample.id) throw new Error('不能更换待恢复的本地样本。');
  if(existing?.nodeId&&existing.coverAssetId)return existing;
  const entry=saveEntry({...existing,id:existing?.id||crypto.randomUUID(),token:existing?.token||
    (crypto.randomUUID()+crypto.randomUUID()).replaceAll('-',''),kind:'custom',sampleId:sample.id,title:sample.title,
    provider:'deepseek',modelId:existing?.modelId||'deepseek-flash',draft:existing?.draft||'',updatedAt:new Date().toISOString()});
  const session=await api.openLocalSample(sample.id,entry.token);
  updateEntry(entry.id,{sessionId:session.session_id,nodeId:existing?.nodeId||session.root.id,provider:session.provider,modelId:session.model_id});
  const manifest=await api.assets(entry.token);
  const cover=manifest.backgrounds[session.root.state_snapshot.location_id||session.root.scene_id];
  if(!manifest.ready||!cover)throw new Error('本地样本图片未就绪，请保留存档并恢复本地素材。');
  return updateEntry(entry.id,{coverAssetId:cover});
}
