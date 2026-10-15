import assert from 'node:assert/strict';
import {test,afterEach} from 'node:test';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../lib/localSamples.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
 .replace('"@/lib/api"',JSON.stringify(new URL('../lib/api.ts',import.meta.url).href))
 .replace('"@/lib/library"',JSON.stringify(new URL('../lib/library.ts',import.meta.url).href));
const {beginLocalSample}=await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
import {readLibrary,updateEntry} from '../lib/library.ts';
const originalFetch=globalThis.fetch,originalDisk=globalThis.localStorage;
afterEach(()=>{globalThis.fetch=originalFetch;globalThis.localStorage=originalDisk;});
const sample={id:'modern',title:'本地故事',era:'modern',intro:'简介'};

test('lost sample response retries the persisted credential and never resets a started game',async()=>{
 const data=new Map();globalThis.localStorage={getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value)};
 const tokens=[];let fail=true;
 globalThis.fetch=async(url,init)=>{
  const saved=readLibrary().entries[0];assert.equal(saved.sampleId,'modern');assert.ok(saved.token);
  const path=new URL(url).pathname;
  if(path==='/local-samples/sessions') {
   tokens.push(JSON.parse(init.body).client_token);if(fail)throw new TypeError('lost response');
   return Response.json({root:{id:'root',state_snapshot:{location_id:'start'}},session_id:'session',provider:'deepseek',model_id:'deepseek-flash'});
  }
  assert.equal(path,'/session/assets');return Response.json({ready:true,backgrounds:{start:'cover'},portraits:{}});
 };
 await assert.rejects(beginLocalSample(sample));const saved=readLibrary().entries[0];fail=false;
 const restored=await beginLocalSample(sample,saved);assert.equal(restored.id,saved.id);assert.deepEqual(tokens,[saved.token,saved.token]);
 assert.equal(restored.coverAssetId,'cover');assert.equal(restored.nodeId,'root');
 updateEntry(restored.id,{nodeId:'later',draft:'保留输入'});
 globalThis.fetch=()=>{throw new Error('completed sample must not open again');};
 const continued=await beginLocalSample(sample,readLibrary().entries[0]);assert.equal(continued.nodeId,'later');assert.equal(continued.draft,'保留输入');
});

test('sample persistence failure stops before sending a session request',async()=>{
 globalThis.localStorage={getItem:()=>null,setItem:()=>{throw new Error('quota');}};
 let called=false;globalThis.fetch=()=>{called=true;throw new Error('network');};
 await assert.rejects(beginLocalSample(sample),/quota/);assert.equal(called,false);
});
