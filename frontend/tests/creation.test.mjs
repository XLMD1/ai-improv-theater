import assert from 'node:assert/strict';
import {test,afterEach} from 'node:test';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../lib/creation.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
 .replace('"@/lib/api"',JSON.stringify(new URL('../lib/api.ts',import.meta.url).href))
 .replace('"@/lib/library"',JSON.stringify(new URL('../lib/library.ts',import.meta.url).href));
const {beginCreation}=await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
import {readLibrary} from '../lib/library.ts';
const originalFetch=globalThis.fetch,originalDisk=globalThis.localStorage;
afterEach(()=>{globalThis.fetch=originalFetch;globalThis.localStorage=originalDisk;});
const request={setting:'古代河运调查',era:'ancient'};

test('a lost creation response keeps the same session token, request and idempotency key',async()=>{
 const data=new Map();globalThis.localStorage={getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value)};
 const keys=[],credentials=[];let fail=true;
 globalThis.fetch=async(url,init)=>{
  const saved=readLibrary().entries[0];assert.ok(saved?.token&&saved.createKey);
  if(new URL(url).pathname==='/story-sessions') {credentials.push(JSON.parse(init.body).client_token);return Response.json({token:saved.token,session_id:'session',provider:'deepseek',model_id:'deepseek-flash'});}
  keys.push(init.headers['Idempotency-Key']);if(fail)throw new TypeError('network unavailable');return Response.json({task_id:'created',status:'queued'});
 };
 await assert.rejects(beginCreation(request));
 const stored=readLibrary().entries[0];assert.deepEqual(stored.createRequest,request);
 fail=false;const recovered=await beginCreation(request,stored);
 assert.deepEqual(keys,[stored.createKey,stored.createKey]);assert.equal(credentials[0],credentials[1]);assert.equal(recovered.creationTaskId,'created');
});

test('an unresolved creation request cannot silently switch to another setting',async()=>{
 const data=new Map();globalThis.localStorage={getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value)};
 globalThis.fetch=async()=>{throw new TypeError('offline');};await assert.rejects(beginCreation(request));
 const saved=readLibrary().entries[0];let calls=0;globalThis.fetch=async()=>{calls++;throw new Error('must not call');};
 await assert.rejects(beginCreation({...request,setting:'另一背景'},saved),/未确认/);assert.equal(calls,0);
});
