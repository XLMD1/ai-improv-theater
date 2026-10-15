"use client";

import { create } from "zustand";
import { api, ApiError, readSSE } from "@/lib/api";
import {findEntry,migrateLegacy,saveEntry,updateEntry} from "@/lib/library";
import {normalizeWorld} from "@/lib/world";
import type { Action, Node, Option, Provider, TreeNode, World,AssetManifest } from "@/lib/types";

type Pending = { key: string; parentId: string; action: Action; runId?: string };

type StoryState = {
  token: string | null;
  provider: Provider;
  modelId: string;
  localSample: boolean;
  node: Node | null;
  world: World | null;
  assets: AssetManifest | null;
  libraryId: string | null;
  tree: TreeNode[];
  pending: Pending | null;
  stage: string;
  streamedText: string;
  streamedOptions: Option[];
  busy: boolean;
  error: string | null;
  draft: string;
  setDraft: (value: string) => void;
  initialize: (id?:string) => Promise<void>;
  newStory: (provider: Provider, modelId: string) => Promise<void>;
  choose: (action: Action) => Promise<void>;
  selectNode: (id: string) => Promise<void>;
  regenerate: () => Promise<void>;
};

let activeId:string|null=null;
const storage = {
  read(name: string) {
    if (!activeId) return sessionStorage.getItem(name);
    const entry=findEntry(activeId);
    if (name==='theater:token') return entry?.token||null;
    if (name==='theater:node') return entry?.nodeId||null;
    if (name==='theater:draft') return entry?.draft||null;
    if (name==='theater:pending') return entry?.pending?JSON.stringify(entry.pending):null;
    return String(entry?.seq?.[name.slice('theater:seq:'.length)]||0);
  },
  write(name: string,value: string) {
    if (!activeId) { sessionStorage.setItem(name,value); return; }
    if (name==='theater:token') updateEntry(activeId,{token:value});
    else if (name==='theater:node') updateEntry(activeId,{nodeId:value});
    else if (name==='theater:draft') updateEntry(activeId,{draft:value});
    else if (name==='theater:pending') updateEntry(activeId,{pending:JSON.parse(value)});
    else updateEntry(activeId,{seq:{...findEntry(activeId)?.seq,[name.slice('theater:seq:'.length)]:Number(value)}});
  },
  remove(name: string) {
    if (!activeId) { sessionStorage.removeItem(name);return; }
    if (name==='theater:pending') updateEntry(activeId,{pending:undefined});
    if (name==='theater:draft') updateEntry(activeId,{draft:''});
  },
};

async function worldFor(token:string,node:Node):Promise<World> {
  return node.state_snapshot?.engine_version==='investigation-1'?normalizeWorld(await api.sessionWorld(token,node.id)):api.world();
}

const stageLabels: Record<string, string> = {
  queued: "正在排队", running: "正在处理你的行动", directing: "正在确认行动",
  writing: "正在准备下一幕", acting: "正在准备对白", reviewing: "正在校验剧情",
};

// These responses reject a turn before creating a run; network/5xx outcomes stay unresolved.
function clearRejectedTurn(error: unknown, pending: Pending | null) {
  if (!pending?.runId && error instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(error.status)) {
    storage.remove("theater:pending");
    return { pending: null, stage: "" };
  }
  return {};
}

function errorMessage(error: unknown) {
  if(error instanceof ApiError&&error.message==='key_not_configured')return "自由输入需要 DeepSeek API 密钥。可以继续使用无需密钥的调查按钮；输入已保留。";
  return error instanceof TypeError ? "无法连接本地服务。输入已保留，请恢复服务后重试连接。" : (error as Error).message;
}

async function listenToRun(token: string, pending: Pending, set: (patch: Partial<StoryState>) => void) {
  const runId = pending.runId;
  if (!runId) return;
  let seq = Number(storage.read(`theater:seq:${runId}`) || 0);
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const run = await api.run(token, runId);
    if (run.status === "completed" && run.node_id) {
      const [node, tree] = await Promise.all([api.node(token, run.node_id), api.tree(token)]);
      const world=await worldFor(token,node);
      storage.write("theater:node", node.id);
      storage.remove("theater:pending");
      storage.remove("theater:draft");
      set({ node, world, tree, pending: null, busy: false, streamedText: "", streamedOptions: [], stage: "", draft: "" });
      return;
    }
    if (run.status === "failed" || run.status === "interrupted") {
      storage.remove("theater:pending");
      set({ pending: null, busy: false, stage: "", error: run.status === "interrupted" ? "任务已中断，输入已保留。可以重新提交行动。" : "本幕未能保存，输入已保留。请检查设置或重新提交行动。" });
      return;
    }
    try {
      await readSSE(token, runId, seq, (event, data, eventSeq) => {
        seq = eventSeq;
        storage.write(`theater:seq:${runId}`, String(seq));
        if (stageLabels[event]) set({ stage: stageLabels[event] });
        if (event === "scene_chunk") set({ streamedText: (useStoryStore.getState().streamedText + String(data.text || "")) });
        if (event === "options") set({ streamedOptions: data.options as Option[] });
      });
    } catch {
      await new Promise(resolve => setTimeout(resolve, 1000 * (attempt + 1)));
    }
  }
  set({ error: "连接中断。刷新页面会从已保存的进度恢复。", busy: false });
}

export const useStoryStore = create<StoryState>((set, get) => ({
  token: null,
  provider: "demo",
  modelId: "demo",
  node: null,
  world: null,
  assets: null,
  libraryId: null,
  localSample: false,
  tree: [],
  pending: null,
  stage: "",
  streamedText: "",
  streamedOptions: [],
  busy: false,
  error: null,
  draft: "",
  setDraft: value => {
    storage.write("theater:draft", value);
    set({ draft: value });
  },

  initialize: async (id) => {
    if (get().busy) return;
    try {
      if (typeof localStorage!=='undefined') {
        migrateLegacy();
        const selectedId=id||get().libraryId||undefined;
        const selected=findEntry(selectedId);
        if (selectedId&&!selected) throw new Error('本机没有这个故事的会话凭据，请返回故事库。');
        activeId=selected?.id||null;
      }
      set({ busy: true, error: null, draft: storage.read("theater:draft") || "", streamedText: "", streamedOptions: [] });
      let token = storage.read("theater:token");
      let node: Node;
      let provider: Provider;
      let modelId: string;
      let requiresAssets=false;
      let localSample=false;
      if (!token) {
        const created = await api.createSession();
        token = created.token;
        node = created.root;
        provider = created.provider;
        modelId = created.model_id;
        if (typeof localStorage!=='undefined') {
          activeId=crypto.randomUUID();
          saveEntry({id:activeId,token,kind:'legacy',title:'雾港最后一夜',provider,modelId,nodeId:node.id,draft:'',updatedAt:new Date().toISOString()});
        }
        storage.write("theater:token", token);
        storage.write("theater:node", node.id);
      } else {
        const id = storage.read("theater:node");
        if (!id) throw new Error("存档节点丢失，请清除本页会话后重试。");
        const [savedNode, session] = await Promise.all([api.node(token, id), api.currentSession(token)]);
        node = savedNode;
        provider = session.provider;
        modelId = session.model_id;
        requiresAssets=Boolean(session.requires_assets);
        localSample=Boolean(session.local_sample);
      }
      const world=await worldFor(token,node);
      const assets=node.state_snapshot?.engine_version==='investigation-1'?await api.assets(token):null;
      if (requiresAssets&&!assets?.ready&&activeId) {
        window.location.replace(`/create?id=${activeId}`);
        return;
      }
      if (activeId) updateEntry(activeId,{title:world.title,provider,modelId});
      const tree = await api.tree(token);
      const stored = storage.read("theater:pending");
      set({ token, node, world, assets, libraryId:activeId, tree, provider, modelId, localSample, busy: Boolean(stored) });
      if (stored) {
        const pending = JSON.parse(stored) as Pending;
        set({ pending, busy: true });
        if (!pending.runId) {
          try {
            const run = await api.turn(token, pending.parentId, pending.action, pending.key);
            pending.runId = run.run_id;
          } catch (error) {
            set(clearRejectedTurn(error, pending));
            throw error;
          }
          storage.write("theater:pending", JSON.stringify(pending));
        }
        await listenToRun(token, pending, set);
      }
    } catch (error) {
      set({ busy: false, error: errorMessage(error) });
    }
  },

  newStory: async (provider, modelId) => {
    if (get().busy || get().pending) throw new Error("当前任务尚未确认，请先恢复任务。");
    set({ busy: true, error: null });
    try {
      const created = await api.createSession(provider, modelId);
      const [tree,world]=await Promise.all([api.tree(created.token),api.world()]);
      if (typeof localStorage!=='undefined') {
        activeId=crypto.randomUUID();
        saveEntry({id:activeId,token:created.token,kind:'legacy',title:world.title,provider:created.provider,modelId:created.model_id,
          nodeId:created.root.id,draft:'',updatedAt:new Date().toISOString()});
        window.history.replaceState(null,'',`/play?id=${activeId}`);
      }
      storage.write("theater:token", created.token);
      storage.write("theater:node", created.root.id);
      storage.remove("theater:pending");
      storage.remove("theater:draft");
      set({ token: created.token, node: created.root, world,assets:null,libraryId:activeId,tree, provider: created.provider,
        modelId: created.model_id, localSample:false, pending: null, busy: false, streamedText: "",
        streamedOptions: [], stage: "", error: null, draft: "" });
    } catch (error) {
      set({ busy: false, error: (error as Error).message });
      throw error;
    }
  },

  choose: async (action) => {
    const { token, node, busy, pending: unresolved } = get();
    if (!token || !node || busy || unresolved) return;
    const pending: Pending = { key: crypto.randomUUID(), parentId: node.id, action };
    storage.write("theater:pending", JSON.stringify(pending));
    set({ pending, busy: true, error: null, streamedText: "", streamedOptions: [], stage: "正在提交选择" });
    try {
      const run = await api.turn(token, node.id, action, pending.key);
      pending.runId = run.run_id;
      storage.write("theater:pending", JSON.stringify(pending));
      set({ pending });
      await listenToRun(token, pending, set);
    } catch (error) {
      set({ ...clearRejectedTurn(error, pending), busy: false, error: errorMessage(error) });
    }
  },

  selectNode: async (id) => {
    const { token, busy, pending } = get();
    if (!token || busy || pending) return;
    set({ busy: true, error: null });
    try {
      const node = await api.node(token, id);
      const world=await worldFor(token,node);
      storage.write("theater:node", id);
      set({ node, world,streamedText: "", streamedOptions: [], error: null });
    } catch (error) {
      set({ error: (error as Error).message });
    } finally {
      set({ busy: false });
    }
  },

  regenerate: async () => {
    const { token, node, busy, pending } = get();
    if (!token || !node?.parent_id || busy || pending) return;
    try {
      const events = await api.nodeEvents(token, node.id);
      const action = events.find(event => event.event_type === "player_action")?.payload;
      if (!action) throw new Error("找不到原始选择。");
      const parent = await api.node(token, node.parent_id);
      storage.write("theater:node", parent.id);
      set({ node: parent });
      await get().choose(action);
    } catch (error) {
      set({ error: (error as Error).message });
    }
  },
}));
