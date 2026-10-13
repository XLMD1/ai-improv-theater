"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, BookOpen, Check, GitBranch, X } from "lucide-react";
import { api } from "@/lib/api";
import { ancestorIds, knownClues } from "@/lib/reading";
import type { Node, TreeNode, World } from "@/lib/types";

export type PanelName = "story" | "clues" | "people" | "history" | "branches" | "reading";
const titles: Record<PanelName, string> = { story: "你的雾港之夜", clues: "已知线索", people: "雾港人物", history: "历史剧情", branches: "分支记录", reading: "阅读设置" };

export function StoryPanel({ name, onClose, children }: { name: PanelName; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog?.showModal();
    return () => { dialog?.close(); document.body.style.overflow = overflow; previous?.focus(); };
  }, []);
  return <dialog ref={ref} className="story-drawer" aria-labelledby="panel-heading" onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => {
    if (event.target !== event.currentTarget) return;
    const box = event.currentTarget.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) onClose();
  }}>
    <header className="drawer-heading"><div><span className="eyebrow">雾港最后一夜</span><h2 id="panel-heading">{titles[name]}</h2></div><button autoFocus className="icon-button" type="button" onClick={onClose} aria-label="关闭面板"><X size={22}/></button></header>
    <div className="drawer-content">{children}</div>
  </dialog>;
}

export function PeoplePanel({ world }: { world: World }) {
  return <div className="people-list">{Object.entries(world.characters).map(([id, person], i) => <section key={id} className="person-entry">
    <span className="person-number">0{i + 1}</span><div><h3>{person.name}</h3><span className="person-role">{person.role}</span><p>{person.goal}</p></div>
  </section>)}</div>;
}

export function CluesPanel({ node }: { node: Node }) {
  const clues = knownClues(node.state_snapshot.flags);
  return <>{clues.length ? <ul className="clue-list">{clues.map(clue => <li key={clue.id}><Check size={18}/><span>{clue.text}</span></li>)}</ul> : <div className="empty-panel"><BookOpen size={32}/><h3>尚未获得线索</h3><p>继续探索，已知的发现会记录在这里。</p></div>}<p className="panel-note">这里只展示当前分支已经发生的记录。</p></>;
}

export function BranchesPanel({ node, world, tree, locked, onSelect }: { node: Node; world: World; tree: TreeNode[]; locked: boolean; onSelect: (id: string) => void }) {
  return <><p className="panel-intro">回到任意一幕，重新决定下一步。旧的故事会完整保留。</p>
    <div className="branch-list">{tree.map(item => <button type="button" key={item.id} className={`branch-item ${item.id === node.id ? "selected" : ""}`} aria-current={item.id === node.id ? "step" : undefined} disabled={locked} onClick={() => onSelect(item.id)} style={{ paddingLeft: `${16 + Math.min(item.depth, 5) * 14}px` }}>
      <GitBranch size={17}/><span><strong>{world.scenes[item.scene_id]?.name || "已保存的场景"}</strong><small>{item.action_label || "故事开始"}</small></span>{item.id === node.id ? <span className="current-mark">当前</span> : <ArrowRight size={16}/>}</button>)}</div>
    <button type="button" className="secondary-button wide-button" disabled={locked || !node.parent_id} onClick={() => node.parent_id && onSelect(node.parent_id)}><ArrowLeft size={18}/> 返回上一幕</button>
  </>;
}

export function HistoryPanel({ token, node, tree, world }: { token: string; node: Node; tree: TreeNode[]; world: World }) {
  const [history, setHistory] = useState<Node[]>([]);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setHistory([]); setError("");
    async function load() {
      try {
        const ids = ancestorIds(tree, node.id);
        const saved = await Promise.all(ids.map(id => id === node.id ? node : api.node(token, id)));
        if (active) setHistory(saved);
      } catch (cause) { if (active) setError((cause as Error).message); }
    }
    void load();
    return () => { active = false; };
  }, [token, node, tree, attempt]);
  return <>{error ? <div role="alert"><p>{error}</p><button className="secondary-button" onClick={() => setAttempt(value => value + 1)}>重试读取</button></div> : !history.length ? <p role="status">正在读取已保存的剧情……</p> : <div className="history-list">{history.map((item, index) => <section key={item.id}>
    <span className="eyebrow">第 {index + 1} 幕</span><h3>{world.scenes[item.scene_id]?.name}</h3><p>{item.rendered_scene.narration}</p>
    {item.rendered_scene.dialogue.map((line, i) => <p key={i}><strong>{world.characters[line.character_id]?.name}：</strong>{line.text}</p>)}
  </section>)}</div>}</>;
}
