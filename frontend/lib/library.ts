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
export type Library = {version:1;entries:LibraryEntry[];currentId?:string};
type Disk = Pick<Storage,'getItem'|'setItem'>;
const key='theater:library:v1';
const fields: (keyof LibraryEntry)[] = ['id','token','kind','title','provider','modelId','sessionId','nodeId','draft','pending','seq','createRequest','createKey','creationTaskId','creationResumeKey','imageKey','imageTaskId','imageResumeKey','updatedAt','coverAssetId','sampleId'];

function clean(entry:LibraryEntry):LibraryEntry {
  return Object.fromEntries(fields.filter(field=>entry[field]!==undefined).map(field=>[field,entry[field]])) as LibraryEntry;
}

export function readLibrary(disk:Disk=localStorage):Library {
  const raw=disk.getItem(key);
  if (!raw) return {version:1,entries:[]};
  const data=JSON.parse(raw) as Library;
  if (data.version!==1 || !Array.isArray(data.entries) || data.entries.some(entry=>
      !entry || typeof entry.id!=='string' || typeof entry.token!=='string' || !['legacy','custom'].includes(entry.kind))) {
    throw new Error('本地故事库版本或内容无法读取，原存档已保留。');
  }
  return {version:1,currentId:data.currentId,entries:data.entries.map(clean)};
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

export function migrateLegacy(disk:Disk=localStorage,session:Disk=sessionStorage):Library {
  const data=readLibrary(disk),token=session.getItem('theater:token');
  if (!token || data.entries.some(entry=>entry.token===token)) return data;
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
