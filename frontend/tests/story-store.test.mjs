import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { afterEach, beforeEach, test } from "node:test";
import ts from "typescript";

// Exercise the real Zustand store; only the browser storage and HTTP boundary are replaced.
const source = await readFile(new URL("../store/story.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target:ts.ScriptTarget.ES2022 } }).outputText
  .replace('"zustand"', JSON.stringify(import.meta.resolve("zustand")))
  .replace('"@/lib/api"', JSON.stringify(new URL("../lib/api.ts", import.meta.url).href))
  .replace('"@/lib/library"',JSON.stringify(new URL('../lib/library.ts',import.meta.url).href))
  .replace('"@/lib/world"',JSON.stringify(new URL('../lib/world.ts',import.meta.url).href));
const { useStoryStore: store } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const originalFetch = globalThis.fetch;
const originalStorage = globalThis.sessionStorage;
const root = { id: "root", parent_id: null, depth: 0, scene_id: "s1" };

beforeEach(() => {
  const data = new Map();
  globalThis.sessionStorage = { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) };
  store.setState({ ...store.getInitialState(), token: "test-token", node: root, tree: [root] }, true);
});
afterEach(() => { globalThis.fetch = originalFetch; globalThis.sessionStorage = originalStorage; });

test("an unresolved request cannot be replaced by a second turn or node navigation", async () => {
  const pending = { key: "original-key", parentId: "root", action: { type: "text", value: "检查窗边" } };
  store.setState({ pending });
  let requests = 0;
  globalThis.fetch = async () => { requests++; throw new Error("unexpected request"); };
  await store.getState().choose({ type: "option", value: "search" });
  await store.getState().selectNode("another-node");
  assert.equal(requests, 0);
  assert.deepEqual(store.getState().pending, pending);
  assert.equal(store.getState().node.id, "root");
});

test("failed submission retains draft and original idempotency key for reconnection", async () => {
  assert.equal(typeof store.getState().setDraft, "function");
  store.getState().setDraft("检查窗边");
  globalThis.fetch = async () => { throw new Error("network unavailable"); };
  await store.getState().choose({ type: "text", value: "检查窗边" });
  assert.equal(store.getState().draft, "检查窗边");
  assert.equal(sessionStorage.getItem("theater:draft"), "检查窗边");
  assert.equal(store.getState().node.id, "root");
  assert.equal(JSON.parse(sessionStorage.getItem("theater:pending")).key, store.getState().pending.key);
});

test("a failed server task preserves input but permits a deliberate new attempt", async () => {
  assert.equal(typeof store.getState().setDraft, "function");
  store.getState().setDraft("检查窗边");
  globalThis.fetch = async url => Response.json(String(url).endsWith("/turns") ? { run_id: "run" } : { status: "failed", error_code: "provider_timeout" });
  await store.getState().choose({ type: "text", value: "检查窗边" });
  assert.equal(store.getState().draft, "检查窗边");
  assert.equal(store.getState().pending, null);
  assert.equal(store.getState().busy, false);
  assert.equal(store.getState().node.id, "root");
});

test("only a completed saved node clears the draft", async () => {
  assert.equal(typeof store.getState().setDraft, "function");
  store.getState().setDraft("检查窗边");
  globalThis.fetch = async url => {
    const path = new URL(url).pathname;
    if (path === "/turns") return Response.json({ run_id: "run" });
    if (path === "/runs/run") return Response.json({ status: "completed", node_id: "child" });
    if (path === "/tree") return Response.json([root, { id: "child", parent_id: "root" }]);
    return Response.json({ id: "child", parent_id: "root" });
  };
  await store.getState().choose({ type: "text", value: "检查窗边" });
  assert.equal(store.getState().draft, "");
  assert.equal(sessionStorage.getItem("theater:draft"), null);
  assert.equal(store.getState().node.id, "child");
  assert.equal(store.getState().pending, null);
});

test("an explicitly rejected turn unlocks settings and preserves the draft", async () => {
  store.getState().setDraft("检查窗边");
  globalThis.fetch = async () => Response.json({ detail: "API key is not configured" }, { status: 409 });
  await store.getState().choose({ type: "text", value: "检查窗边" });
  assert.equal(store.getState().pending, null);
  assert.equal(sessionStorage.getItem("theater:pending"), null);
  assert.equal(store.getState().draft, "检查窗边");
  assert.equal(store.getState().node.id, "root");
});

test("refresh recovery resubmits the same key and commits only the saved result", async () => {
  const pending = { key: "original-key", parentId: "root", action: { type: "text", value: "检查窗边" } };
  sessionStorage.setItem("theater:token", "test-token");
  sessionStorage.setItem("theater:node", "root");
  sessionStorage.setItem("theater:pending", JSON.stringify(pending));
  store.getState().setDraft("检查窗边");
  const keys = [];
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    if (path === "/turns") { keys.push(init.headers["Idempotency-Key"]); return Response.json({ run_id: "run" }); }
    if (path === "/world") return Response.json({ title: "测试世界" });
    if (path === "/session") return Response.json({ provider: "demo", model_id: "demo" });
    if (path === "/tree") return Response.json([root, { id: "child", parent_id: "root" }]);
    if (path === "/runs/run") return Response.json({ status: "completed", node_id: "child" });
    return Response.json(path === "/nodes/root" ? root : { id: "child", parent_id: "root" });
  };
  await store.getState().initialize();
  assert.deepEqual(keys, ["original-key"]);
  assert.equal(store.getState().node.id, "child");
  assert.equal(store.getState().pending, null);
  assert.equal(store.getState().draft, "");
});

test("an ambiguous server failure keeps the key until recovery confirms its outcome", async () => {
  store.getState().setDraft("检查窗边");
  globalThis.fetch = async () => Response.json({ detail: "unavailable" }, { status: 503 });
  await store.getState().choose({ type: "text", value: "检查窗边" });
  assert.ok(store.getState().pending);
  assert.equal(JSON.parse(sessionStorage.getItem("theater:pending")).key, store.getState().pending.key);
  assert.equal(store.getState().draft, "检查窗边");
  assert.equal(store.getState().node.id, "root");
});


test("reconnect retains this tab's selected story after another tab selects one", async () => {
  const previous=globalThis.localStorage;
  const data=new Map();
  globalThis.localStorage={getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value)};
  try {
    const entries=['a','b'].map(id=>({id,token:'token-'+id,kind:'legacy',title:id,provider:'demo',modelId:'demo',nodeId:'root-'+id,draft:'',updatedAt:'now'}));
    localStorage.setItem('theater:library:v1',JSON.stringify({version:1,entries,currentId:'b'}));
    store.setState({libraryId:'a'});
    const credentials=[];
    globalThis.fetch=async (url,init)=>{
      credentials.push(init?.headers?.Authorization);
      const path=new URL(url).pathname;
      if(path==='/session')return Response.json({provider:'demo',model_id:'demo'});
      if(path==='/world')return Response.json({title:'a'});
      if(path==='/tree')return Response.json([]);
      return Response.json({id:'root-a',state_snapshot:{},rendered_scene:{}});
    };
    await store.getState().initialize();
    assert.equal(store.getState().token,'token-a');
    assert.equal(store.getState().libraryId,'a');
    assert.ok(credentials.every(value=>value==='Bearer token-a'||value===undefined));
  } finally {globalThis.localStorage=previous;}
});
