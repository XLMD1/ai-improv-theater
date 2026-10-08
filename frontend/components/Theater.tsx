"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { ArrowLeft, GitBranch, RotateCcw, Send, Settings, Sparkles, Theater as TheaterIcon } from "lucide-react";
import { CharacterPortrait, SceneArt } from "./SceneArt";
import { LocalSettingsDialog } from "./LocalSettingsDialog";
import { useStoryStore } from "@/store/story";
import type { CharacterId } from "@/lib/types";

function RelationshipGraph({ relations, names }: { relations: Record<string, number>; names: Record<string, string> }) {
  const edges = [["c1:c2", "林岚 · 周砚"], ["c1:c3", "林岚 · 沈知夏"], ["c2:c3", "周砚 · 沈知夏"]] as const;
  return (
    <section className="side-card" aria-labelledby="relationship-heading">
      <div className="section-title"><h2 id="relationship-heading">人物关系</h2><span>实时状态</span></div>
      <div className="relation-names"><span>{names.c1}</span><span>{names.c2}</span><span>{names.c3}</span></div>
      <svg className="relation-lines" viewBox="0 0 280 70" aria-hidden="true">
        <path d="M36 56L140 10 244 56 36 56" fill="none" stroke="#677e86" strokeWidth="1.5"/>
        <circle cx="140" cy="10" r="4" fill="#dbac68"/><circle cx="36" cy="56" r="4" fill="#dbac68"/><circle cx="244" cy="56" r="4" fill="#dbac68"/>
      </svg>
      <ul className="relation-list">
        {edges.map(([key, label]) => <li key={key}><span>{label}</span><strong>{relations[key] > 0 ? "+" : ""}{relations[key] ?? 0}</strong></li>)}
      </ul>
    </section>
  );
}

export default function Theater() {
  const { node, world, tree, provider, modelId, busy, error, stage, streamedText, streamedOptions, initialize, newStory, choose, selectNode, regenerate } = useStoryStore();
  const [freeText, setFreeText] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [visibleText, setVisibleText] = useState("");
  const initialized = useRef(false);

  useEffect(() => { if (!initialized.current) { initialized.current = true; void initialize(); } }, [initialize]);
  useEffect(() => {
    if (!streamedText) { setVisibleText(""); return; }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setVisibleText(streamedText); return; }
    const timer = window.setInterval(() => setVisibleText(previous => streamedText.slice(0, Math.min(previous.length + 2, streamedText.length))), 24);
    return () => window.clearInterval(timer);
  }, [streamedText]);

  const submitText = (event: FormEvent) => {
    event.preventDefault();
    const value = freeText.trim();
    if (!value || value.length > 500 || busy) return;
    setFreeText("");
    void choose({ type: "text", value });
  };

  if (!node || !world) {
    return <main className="loading-screen"><div className="brand-mark"><TheaterIcon size={24}/></div><p>{error || "正在打开雾港的故事……"}</p><button onClick={() => void initialize()}>重试连接</button></main>;
  }

  const scene = node.rendered_scene;
  const sceneName = world.scenes[node.scene_id]?.name || node.scene_id;
  const currentParticipants = [...new Set(scene.dialogue.map(line => line.character_id))] as CharacterId[];
  const terminal = node.scene_id.startsWith("e");
  const options = busy ? streamedOptions : scene.options;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#story-content">跳到剧情</a>
      <header className="topbar">
        <div className="brand"><span className="brand-mark"><TheaterIcon size={22} aria-hidden="true"/></span><div><strong>AI 即兴剧场</strong><small>THE IMPROV THEATER</small></div></div>
        <div className="topbar-center"><span className="eyebrow">正在上演</span><strong>{world.title}</strong></div>
        <div className="topbar-status"><span className="demo-badge">{provider === "demo" ? "确定性 Demo · 无 AI 调用" : `${provider === "openai" ? "OpenAI" : "DeepSeek"} · ${modelId}`}</span><span className="status-dot"/><span>{busy ? stage : terminal ? "故事终章" : "等待你的选择"}</span><button type="button" className="topbar-settings" onClick={() => setSettingsOpen(true)} disabled={busy} aria-label="打开本地模型设置"><Settings size={17} aria-hidden="true"/> 设置</button></div>
      </header>

      <div className="layout">
        <main id="story-content" className="story-column">
          <div className="scene-heading"><div><span className="eyebrow">CHAPTER {String(node.depth + 1).padStart(2, "0")}</span><h1>{sceneName}</h1></div><span className="scene-tag">{terminal ? "结局" : "开放剧情"}</span></div>

          <div className="stage-frame">
            <SceneArt sceneId={node.scene_id}/>
            <div className="stage-vignette"/>
            <div className="stage-caption"><span>雾港 · 最后一夜</span><span>SCENE {String(node.depth + 1).padStart(2, "0")}</span></div>
            <div className="portrait-row">
              {currentParticipants.map(id => <div className="portrait-wrap" key={id}><CharacterPortrait id={id} name={world.characters[id].name}/><span>{world.characters[id].name}</span></div>)}
            </div>
          </div>

          <section className="story-panel" aria-live="polite" aria-busy={busy}>
            <div className="story-panel-top"><span className="eyebrow">STORY</span><span>{busy ? stage : scene.fallback ? "安全过渡幕" : "已保存 · 可回放"}</span></div>
            {busy && !visibleText ? <p className="generating"><Sparkles size={17} aria-hidden="true"/> {stage || "正在生成下一幕"}……</p> :
              busy ? <p className="stream-text">{visibleText}<span className="caret" aria-hidden="true"/></p> : <>
                <p className="narration">{scene.narration}</p>
                <div className="dialogue-list">{scene.dialogue.map((line, index) => <div className="dialogue" key={`${line.character_id}-${index}`}><strong>{world.characters[line.character_id].name}</strong><p>{line.text}</p></div>)}</div>
              </>}
          </section>

          {error && <div className="error-banner" role="alert">{error}</div>}

          <section className="choices" aria-labelledby="choice-heading">
            <div className="choice-heading"><div><span className="eyebrow">YOUR TURN</span><h2 id="choice-heading">{terminal ? "这段故事已结束" : "接下来，你会怎么做？"}</h2></div><span>{terminal ? "可回看其他分支" : "选择或自由输入"}</span></div>
            {!terminal && <>
              <div className="option-list">{options.map((option, index) => <button disabled={busy} className="option-button" onClick={() => void choose({ type: "option", value: option.id })} key={option.id}><span className="option-index">{String(index + 1).padStart(2, "0")}</span><span>{option.label}</span><span aria-hidden="true" className="option-arrow">↗</span></button>)}</div>
              <form className="free-form" onSubmit={submitText}><label htmlFor="free-action">或者，写下你的行动</label><div className="input-row"><input id="free-action" value={freeText} onChange={event => setFreeText(event.target.value)} maxLength={500} disabled={busy} placeholder="例如：把航海日志交给沈知夏……"/><button type="submit" disabled={busy || !freeText.trim()} aria-label="发送自由行动"><Send size={18}/></button></div><small>{freeText.length}/500</small></form>
            </>}
          </section>
        </main>

        <aside className="sidebar" aria-label="存档与角色状态">
          <section className="side-card session-card"><span className="eyebrow">CURRENT RUN</span><h2>你的雾港之夜</h2><p>每个选择都会成为一个可回看的分支。</p><div className="session-stats"><div><strong>{node.depth}</strong><span>已走幕数</span></div><div><strong>{tree.length - 1}</strong><span>已存分支</span></div></div></section>
          <RelationshipGraph relations={node.state_snapshot.relations} names={{ c1: world.characters.c1.name, c2: world.characters.c2.name, c3: world.characters.c3.name }}/>
          <section className="side-card" aria-labelledby="branch-heading"><div className="section-title"><h2 id="branch-heading"><GitBranch size={17} aria-hidden="true"/> 分支存档</h2><span>{tree.length} 个节点</span></div><div className="branch-list">{tree.map(item => <button key={item.id} className={`branch-item ${item.id === node.id ? "selected" : ""}`} style={{ paddingLeft: `${12 + Math.min(item.depth, 6) * 12}px` }} onClick={() => void selectNode(item.id)} disabled={busy} aria-current={item.id === node.id ? "step" : undefined}><span className="branch-dot"/><span className="branch-label"><strong>{world.scenes[item.scene_id]?.name || item.scene_id}</strong><span>{item.action_label}</span></span><small>#{item.depth + 1}</small></button>)}</div><div className="branch-actions"><button onClick={() => node.parent_id && void selectNode(node.parent_id)} disabled={!node.parent_id || busy}><ArrowLeft size={15} aria-hidden="true"/> 回到上一幕</button><button onClick={() => void regenerate()} disabled={!node.parent_id || busy}><RotateCcw size={15} aria-hidden="true"/> 重新生成</button></div></section>
          <p className="aside-note">{provider === "demo" ? "确定性 Demo 只验证状态规则、分支隔离和原样回放，不代表 AI 生成质量。" : "当前会话使用固定模型；候选稿通过结构与状态校验后保存，旧节点回放不再调用模型。"}</p>
        </aside>
      </div>
      {settingsOpen && <LocalSettingsDialog currentProvider={provider} currentModel={modelId} hasProgress={tree.length > 1}
        onClose={() => setSettingsOpen(false)} onNewStory={newStory}/>}
    </div>
  );
}
