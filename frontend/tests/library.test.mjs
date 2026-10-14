import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readLibrary,saveEntry,migrateLegacy,updateEntry} from '../lib/library.ts';

function storage() { const data=new Map(); return {getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key)}; }
const entry=(id,token)=>({id,token,kind:'legacy',title:'测试故事',provider:'demo',modelId:'demo',nodeId:'root-'+id,draft:'',updatedAt:'2026-10-14'});

test('a persistent library isolates each story draft, token, node and pending action',()=>{
 const disk=storage(); saveEntry(entry('a','token-a'),disk); saveEntry(entry('b','token-b'),disk);
 updateEntry('a',{draft:'检查窗口',pending:{key:'key-a',parentId:'root-a',action:{type:'text',value:'检查窗口'}}},disk);
 const restored=readLibrary(disk);
 assert.equal(restored.entries.length,2); assert.equal(restored.entries.find(e=>e.id==='b').token,'token-b');
 assert.equal(restored.entries.find(e=>e.id==='b').draft,''); assert.equal(restored.entries.find(e=>e.id==='a').pending.key,'key-a');
});

test('legacy migration keeps the current saved node and original unresolved key and runs once',()=>{
 const disk=storage(),session=storage(); session.setItem('theater:token','legacy-token'); session.setItem('theater:node','saved-node');
 session.setItem('theater:draft','未发送的行动');session.setItem('theater:pending',JSON.stringify({key:'original',parentId:'parent',action:{type:'text',value:'行动'}}));
 migrateLegacy(disk,session); migrateLegacy(disk,session);
 const result=readLibrary(disk);assert.equal(result.entries.length,1);assert.equal(result.entries[0].nodeId,'saved-node');
 assert.equal(result.entries[0].pending.key,'original');assert.equal(result.entries[0].draft,'未发送的行动');
});

test('library persistence has a fixed field allowlist and never saves API keys',()=>{
 const disk=storage();saveEntry({...entry('a','session-credential'),apiKey:'PRIVATE_API_KEY',authorization:'Bearer PRIVATE'},disk);
 const raw=disk.getItem('theater:library:v1');assert.ok(!raw.includes('PRIVATE'));assert.ok(raw.includes('session-credential'));
});

test('a quota failure is surfaced before a caller can submit an unrecorded task',()=>{
 const disk={getItem:()=>null,setItem:()=>{throw new Error('quota');}};
 assert.throws(()=>saveEntry(entry('a','token'),disk),/quota/);
});
