"use client";

import { create } from "zustand";
import { api, readSSE } from "@/lib/api";
import type { Action, Node, Option, TreeNode, World } from "@/lib/types";

type Pending = { key: string; parentId: string; action: Action; runId?: string };

type StoryState = {
  token: string | null;
  node: Node | null;
  world: World | null;
  tree: TreeNode[];
  pending: Pending | null;
  stage: string;
  streamedText: string;
  streamedOptions: Option[];
  busy: boolean;
  error: string | null;
  initialize: () => Promise<void>;
  choose: (action: Action) => Promise<void>;
  selectNode: (id: string) => Promise<void>;
  regenerate: () => Promise<void>;
};

const storage = {
  read(name: string) { return sessionStorage.getItem(name); },
  write(name: string, value: string) { sessionStorage.setItem(name, value); },
  remove(name: string) { sessionStorage.removeItem(name); },
};

const stageLabels: Record<string, string> = {
  queued: "正在排队", running: "开始构思", directing: "导演安排下一幕",
  writing: "编剧编排剧情", acting: "角色准备对白", reviewing: "校验剧情一致性",
};

async function listenToRun(token: string, pending: Pending, set: (patch: Partial<StoryState>) => void) {
  const runId = pending.runId;
  if (!runId) return;
  let seq = Number(storage.read(`theater:seq:${runId}`) || 0);
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const run = await api.run(token, runId);
    if (run.status === "completed" && run.node_id) {
      const [node, tree] = await Promise.all([api.node(token, run.node_id), api.tree(token)]);
      storage.write("theater:node", node.id);
      storage.remove("theater:pending");
      set({ node, tree, pending: null, busy: false, streamedText: "", streamedOptions: [], stage: "" });
      return;
    }
    if (run.status === "failed" || run.status === "interrupted") {
      storage.remove("theater:pending");
      set({ pending: null, busy: false, stage: "", error: "本幕未提交，请重新选择。" });
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
  node: null,
  world: null,
  tree: [],
  pending: null,
  stage: "",
  streamedText: "",
  streamedOptions: [],
  busy: false,
  error: null,

  initialize: async () => {
    try {
      set({ busy: true, error: null });
      const world = await api.world();
      let token = storage.read("theater:token");
      let node: Node;
      if (!token) {
        const created = await api.createSession();
        token = created.token;
        node = created.root;
        storage.write("theater:token", token);
        storage.write("theater:node", node.id);
      } else {
        const id = storage.read("theater:node");
        if (!id) throw new Error("存档节点丢失，请清除本页会话后重试。");
        node = await api.node(token, id);
      }
      const tree = await api.tree(token);
      set({ token, node, world, tree, busy: false });
      const stored = storage.read("theater:pending");
      if (stored) {
        const pending = JSON.parse(stored) as Pending;
        set({ pending, busy: true });
        if (!pending.runId) {
          const run = await api.turn(token, pending.parentId, pending.action, pending.key);
          pending.runId = run.run_id;
          storage.write("theater:pending", JSON.stringify(pending));
        }
        await listenToRun(token, pending, set);
      }
    } catch (error) {
      set({ busy: false, error: (error as Error).message });
    }
  },

  choose: async (action) => {
    const { token, node, busy } = get();
    if (!token || !node || busy) return;
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
      set({ busy: false, error: (error as Error).message });
    }
  },

  selectNode: async (id) => {
    const { token, busy } = get();
    if (!token || busy) return;
    try {
      const node = await api.node(token, id);
      storage.write("theater:node", id);
      set({ node, streamedText: "", streamedOptions: [], error: null });
    } catch (error) {
      set({ error: (error as Error).message });
    }
  },

  regenerate: async () => {
    const { token, node, busy } = get();
    if (!token || !node?.parent_id || busy) return;
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
