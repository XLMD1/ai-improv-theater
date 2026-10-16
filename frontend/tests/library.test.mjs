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

test('legacy migration keeps the current saved node and original unresolved key and runs once',async()=>{
 const disk=storage(),session=storage(); session.setItem('theater:token','legacy-token'); session.setItem('theater:node','saved-node');
 session.setItem('theater:draft','未发送的行动');session.setItem('theater:pending',JSON.stringify({key:'original',parentId:'parent',action:{type:'text',value:'行动'}}));
 await migrateLegacy(disk,session); await migrateLegacy(disk,session);
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


test('deleting a saved game removes its credentials and progress but preserves other games',async()=>{
 const {removeEntry}=await import('../lib/library.ts');
 const disk=storage(),session=storage();
 const keep=entry('keep','keep-token');saveEntry(keep,disk);
 saveEntry({...entry('remove','remove-token'),draft:'private draft',pending:{key:'pending-key',parentId:'root-remove',action:{type:'text',value:'行动'}}},disk);
 const result=await await removeEntry('remove',disk,session);
 assert.deepEqual(result.entries,[keep]);assert.equal(result.currentId,undefined);
 assert.deepEqual(readLibrary(disk).entries,[keep]);assert.equal(readLibrary(disk).currentId,undefined);
 const raw=disk.getItem('theater:library:v1');
 for(const value of ['remove-token','private draft','pending-key','root-remove']) assert.ok(!raw.includes(value));
 assert.throws(()=>updateEntry('remove',{draft:'late write'},disk),/未找到/);
});

test('deleting another game preserves the current game and is safe to repeat',async()=>{
 const {removeEntry}=await import('../lib/library.ts');
 const disk=storage(),session=storage();saveEntry(entry('remove','remove-token'),disk);saveEntry(entry('keep','keep-token'),disk);
 await removeEntry('remove',disk,session);const result=await await removeEntry('remove',disk,session);
 assert.equal(result.currentId,'keep');assert.deepEqual(result.entries,[entry('keep','keep-token')]);
});

test('a deleted migrated game cannot be imported again on refresh',async()=>{
 const {removeEntry}=await import('../lib/library.ts');
 const disk=storage(),session=storage();session.setItem('theater:token','legacy-token');session.setItem('theater:node','legacy-node');
 session.setItem('theater:draft','legacy draft');session.setItem('theater:pending',JSON.stringify({key:'old-key',parentId:'legacy-node',action:{type:'text',value:'行动'}}));
 const migrated=await migrateLegacy(disk,session);await removeEntry(migrated.entries[0].id,disk,session);
 assert.deepEqual((await migrateLegacy(disk,session)).entries,[]);
 for(const name of ['token','node','draft','pending'])assert.equal(session.getItem('theater:'+name),null);
});

test('deleting a game preserves unrelated legacy recovery data',async()=>{
 const {removeEntry}=await import('../lib/library.ts');
 const disk=storage(),session=storage();saveEntry(entry('remove','remove-token'),disk);
 session.setItem('theater:token','other-token');session.setItem('theater:draft','other draft');
 await removeEntry('remove',disk,session);
 assert.equal(session.getItem('theater:token'),'other-token');assert.equal(session.getItem('theater:draft'),'other draft');
});

test('a failed deletion write reports failure and leaves the library recoverable',async()=>{
 const {removeEntry}=await import('../lib/library.ts');
 const disk=storage(),session=storage();saveEntry(entry('keep','keep-token'),disk);
 const before=disk.getItem('theater:library:v1');
 const failing={getItem:disk.getItem,setItem:()=>{throw new Error('storage unavailable');}};
 await assert.rejects(()=>removeEntry('keep',failing,session),/storage unavailable/);
 assert.equal(disk.getItem('theater:library:v1'),before);
});


test('a different tab cannot resurrect a deleted legacy game with its old credentials',async()=>{
 const {removeEntry}=await import('../lib/library.ts');
 const disk=storage(),first=storage(),second=storage();
 for(const tab of [first,second]) {tab.setItem('theater:token','old-shared-token');tab.setItem('theater:node','old-node');tab.setItem('theater:draft','old draft');}
 const migrated=await migrateLegacy(disk,first);await removeEntry(migrated.entries[0].id,disk,first);
 saveEntry(entry('unrelated','unrelated-token'),disk);
 const refreshed=await migrateLegacy(disk,second);
 assert.deepEqual(refreshed.entries,[entry('unrelated','unrelated-token')]);
 assert.equal(second.getItem('theater:token'),null);
 assert.ok(!disk.getItem('theater:library:v1').includes('old-shared-token'));
});
