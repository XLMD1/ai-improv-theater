import type {Action,Provider} from './types';

export type PendingAction = {key:string;parentId:string;action:Action;runId?:string};
export type CreationRequest = {setting:string;era:'ancient'|'modern'|'future'};
export type LibraryEntry = {
  id:string;token:string;kind:'legacy'|'custom';title:string;provider:Provider;modelId:string;
  sessionId?:string;nodeId?:string;draft:string;pending?:PendingAction;seq?:Record<string,number>;
  createRequest?:CreationRequest;createKey?:string;creationTaskId?:string;creationResumeKey?:string;
  imageKey?:string;imageTaskId?:string;imageResumeKey?:string;updatedAt:string;
  coverAssetId?:string;sampleId?:'ancient'|'modern'|'future';
};
export type Library = {version:1;entries:LibraryEntry[];currentId?:string;removedTokenHashes?:string[]};
type Disk = Pick<Storage,'getItem'|'setItem'>;
type LegacyDisk = Pick<Storage,'getItem'|'removeItem'>;
const key='theater:library:v1';
const fields: (keyof LibraryEntry)[] = ['id','token','kind','title','provider','modelId','sessionId','nodeId','draft','pending','seq','createRequest','createKey','creationTaskId','creationResumeKey','imageKey','imageTaskId','imageResumeKey','updatedAt','coverAssetId','sampleId'];

function clean(entry:LibraryEntry):LibraryEntry {
  return Object.fromEntries(fields.filter(field=>entry[field]!==undefined).map(field=>[field,entry[field]])) as LibraryEntry;
}

export function readLibrary(disk:Disk=localStorage):Library {
  const raw=disk.getItem(key);
  if (!raw) return {version:1,entries:[]};
  const data=JSON.parse(raw) as Library;
  if (data.version!==1 || !Array.isArray(data.entries) ||
      (data.removedTokenHashes!==undefined&&(!Array.isArray(data.removedTokenHashes)||data.removedTokenHashes.some(value=>typeof value!=='string'))) || data.entries.some(entry=>
      !entry || typeof entry.id!=='string' || typeof entry.token!=='string' || !['legacy','custom'].includes(entry.kind))) {
    throw new Error('本地故事库版本或内容无法读取，原存档已保留。');
  }
  return {version:1,currentId:data.currentId,entries:data.entries.map(clean),...(data.removedTokenHashes?{removedTokenHashes:data.removedTokenHashes}:{})};
}

export function saveEntry(entry:LibraryEntry,disk:Disk=localStorage):LibraryEntry {
  const data=readLibrary(disk);
  const saved=clean(entry);
  const index=data.entries.findIndex(item=>item.id===entry.id);
  if (index===-1) data.entries.push(saved); else data.entries[index]=saved;
  data.currentId=entry.id;
  disk.setItem(key,JSON.stringify(data));
  return saved;
}

export function updateEntry(id:string,patch:Partial<LibraryEntry>,disk:Disk=localStorage):LibraryEntry {
  const current=readLibrary(disk).entries.find(entry=>entry.id===id);
  if (!current) throw new Error('本机未找到该故事凭据，请从故事库选择已有故事。');
  return saveEntry({...current,...patch,id,updatedAt:new Date().toISOString()},disk);
}

async function tokenHash(token:string):Promise<string> {
  const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(token));
  return Array.from(new Uint8Array(bytes),byte=>byte.toString(16).padStart(2,'0')).join('');
}

function clearLegacy(session:LegacyDisk) {
  for (const name of ['token','node','draft','pending']) session.removeItem('theater:'+name);
}

export async function removeEntry(id:string,disk:Disk=localStorage,session:LegacyDisk=sessionStorage):Promise<Library> {
  const initial=readLibrary(disk),entry=initial.entries.find(item=>item.id===id);
  if (!entry) return initial;
  const hash=await tokenHash(entry.token);
  // Read again after hashing so concurrent updates to other games are preserved.
  const data=readLibrary(disk),current=data.entries.find(item=>item.id===id);
  if (!current) return data;
  if (current.token!==entry.token) throw new Error('记录已更新，请重新选择后删除。');
  if (session.getItem('theater:token')===entry.token) clearLegacy(session);
  data.entries=data.entries.filter(item=>item.id!==id);
  if (data.currentId===id) delete data.currentId;
  // Only a one-way fingerprint remains; old tabs cannot re-import the credential.
  data.removedTokenHashes=[...new Set([...(data.removedTokenHashes||[]),hash])];
  disk.setItem(key,JSON.stringify(data));
  return data;
}

export async function migrateLegacy(disk:Disk=localStorage,session:LegacyDisk=sessionStorage):Promise<Library> {
  const token=session.getItem('theater:token');
  if (!token) return readLibrary(disk);
  const hash=await tokenHash(token),data=readLibrary(disk);
  if (data.removedTokenHashes?.includes(hash)) {clearLegacy(session);return data;}
  if (data.entries.some(entry=>entry.token===token)) return data;
  const pending=session.getItem('theater:pending');
  saveEntry({id:crypto.randomUUID(),token,kind:'legacy',title:'雾港最后一夜',provider:'demo',modelId:'demo',
    nodeId:session.getItem('theater:node')||undefined,draft:session.getItem('theater:draft')||'',
    ...(pending?{pending:JSON.parse(pending) as PendingAction}:{}),updatedAt:new Date().toISOString()},disk);
  return readLibrary(disk);
}

export function findEntry(id?:string):LibraryEntry|undefined {
  const data=readLibrary();
  return data.entries.find(entry=>entry.id===(id||data.currentId));
}
