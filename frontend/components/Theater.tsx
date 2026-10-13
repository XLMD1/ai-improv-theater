"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen, BriefcaseBusiness, Check, ChevronDown, Clock3, GitBranch, LoaderCircle, PencilLine, Settings, SlidersHorizontal, Users, VolumeX } from "lucide-react";
import { LocalSettingsDialog } from "./LocalSettingsDialog";
import { SceneReader, type ReadingSpeed } from "./SceneReader";
import { BranchesPanel, CluesPanel, HistoryPanel, PeoplePanel, StoryPanel, type PanelName } from "./StoryPanel";
import { useStoryStore } from "@/store/story";
import { knownClues } from "@/lib/reading";

const art: Record<string, { file: string; focus: string }> = {
  harbor: { file: "harbor", focus: "42% 45%" }, archive: { file: "archive", focus: "50% 48%" },
  dock: { file: "dock", focus: "48% 50%" }, tower: { file: "tower", focus: "50% 45%" },
  lighthouse: { file: "lighthouse", focus: "55% 46%" }, dawn: { file: "dawn", focus: "50% 45%" },
};

export default function Theater() {
  const { node, world, tree, token, provider, modelId, busy, pending, error, stage, draft, setDraft, initialize, newStory, choose, selectNode } = useStoryStore();
  const [panel, setPanel] = useState<PanelName | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [speed, setSpeed] = useState<ReadingSpeed>("normal");
  const [reduceMotion, setReduceMotion] = useState(false);
  const [systemReduced, setSystemReduced] = useState(false);
  const [failedImage, setFailedImage] = useState<string | null>(null);
  const [imageAttempt, setImageAttempt] = useState(0);
  const initialized = useRef(false);

  useEffect(() => { if (!initialized.current) { initialized.current = true; void initialize(); } }, [initialize]);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setSystemReduced(media.matches);
    update(); media.addEventListener("change", update);
    try {
      const saved = JSON.parse(localStorage.getItem("theater:reading") || "{}");
      if (["instant", "normal", "slow"].includes(saved.speed)) setSpeed(saved.speed);
      setReduceMotion(saved.reduceMotion === true);
    } catch { /* Default preferences remain usable when storage is unavailable. */ }
    return () => media.removeEventListener("change", update);
  }, []);

  const saveReading = (nextSpeed: ReadingSpeed, nextReduced: boolean) => {
    setSpeed(nextSpeed); setReduceMotion(nextReduced);
    try { localStorage.setItem("theater:reading", JSON.stringify({ speed: nextSpeed, reduceMotion: nextReduced })); } catch { /* Keep preferences for this visit. */ }
  };
  const locked = busy || Boolean(pending);
  const openSettings = () => { setPanel(null); setSettingsOpen(true); };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!draft.trim() || draft.length > 500 || locked) return;
    void choose({ type: "text", value: draft.trim() });
  };

  if (!node || !world) return <main className="loading-screen">
    <img src="/art/harbor.webp" alt="" className="loading-art"/>
    <div className="loading-content"><span className="eyebrow">AI 即兴剧场</span><h1>雾港最后一夜</h1><p role={error ? "alert" : "status"}>{error || "正在打开你的故事……"}</p>
      {error ? <button type="button" className="primary-button" disabled={busy} onClick={() => void initialize()}>重试连接 <ArrowRight size={18}/></button> : <LoaderCircle className="spinner" aria-hidden="true"/>}
    </div>
  </main>;

  const scene = node.rendered_scene;
  const location = world.scenes[node.scene_id];
  const artwork = art[location?.background] || art.harbor;
  const imageSrc = `/art/${artwork.file}.webp`;
  const terminal = Boolean(node.state_snapshot.ending_id) || scene.options.length === 0;
  const replaying = tree.some(item => item.parent_id === node.id);
  const clueCount = knownClues(node.state_snapshot.flags).length;
  const status = busy ? (stage || "正在读取") : pending ? "等待恢复" : replaying ? "正在回看" : "已保存";

  return <div className={`cinema-app ${reduceMotion || systemReduced ? "reduce-motion" : ""}`}>
    <a className="skip-link" href="#story-content">跳到剧情与行动</a>
    <div className="cinema-backdrop" aria-hidden="true"><img key={`${imageSrc}:${imageAttempt}`} src={`${imageSrc}${imageAttempt ? `?retry=${imageAttempt}` : ""}`} style={{ objectPosition: artwork.focus }} alt="" fetchPriority="high" onError={() => setFailedImage(imageSrc)} onLoad={() => setFailedImage(null)}/></div>
    <header className="cinema-topbar">
      <button type="button" className="story-home quiet-button" onClick={() => setPanel("story")}><ArrowLeft size={21}/> <span>故事</span></button>
      <div className="cinema-title"><h1>{world.title}</h1><span className="title-slash">/</span><span className="topbar-location">{location?.name}</span></div>
      <div className="save-state" role="status">{busy ? <LoaderCircle size={14} className="spinner"/> : pending ? <Clock3 size={14}/> : <Check size={14}/>}<span>{status}</span></div>
      <button type="button" className="icon-button settings-trigger" onClick={openSettings} disabled={locked} aria-label="打开设置"><Settings size={21}/></button>
    </header>

    <section className="scene-space" aria-label={`${location?.name || "当前地点"}场景`}>
      <div className="scene-location"><span className="eyebrow">{terminal ? "故事终章" : "雾港 · 最后一夜"}</span><span>{location?.name}</span></div>
      {artwork.file === "harbor" && <button type="button" className="scene-hotspot" onClick={() => setPanel("people")} aria-label="查看林岚及人物资料"><span className="hotspot-ring"/><span>林岚 <small>人物资料</small></span></button>}
      {failedImage === imageSrc && <div className="image-error" role="status"><p>场景图片暂时无法加载</p><button className="secondary-button" onClick={() => setImageAttempt(value => value + 1)}>重新加载图片</button></div>}
      <span className="scene-mode">{provider === "demo" ? "内置 Demo" : "DeepSeek 故事"}<span/>无声，亦有回响</span>
    </section>

    <main id="story-content" className="cinema-console">
      <div className="console-topline"><h2><BookOpen size={21}/>{terminal ? "终章记录" : "现场记录"}</h2><div className="reader-tools">
        <button type="button" className="quiet-button" onClick={() => setPanel("history")}><Clock3 size={17}/>历史</button>
        <button type="button" className="quiet-button" onClick={() => setPanel("reading")}><SlidersHorizontal size={17}/><span>文字速度</span><ChevronDown size={13}/></button>
      </div></div>
      {replaying && <p className="replay-notice"><GitBranch size={15}/> 正在回看已保存的一幕。{!terminal && "从这里行动，将开启新的分支。"}</p>}
      <div className="story-and-actions">
        <section aria-label="已保存的剧情"><SceneReader key={node.id} scene={scene} world={world} speed={speed} reducedMotion={reduceMotion || systemReduced}/>{scene.fallback && <p className="panel-note">本幕使用已保存的安全过渡内容。</p>}</section>
        <section className="scene-actions" aria-label={terminal ? "结局操作" : "选择你的行动"} aria-busy={busy}>
          {terminal ? <><h3 className="ending-title">{location?.name}</h3><p className="ending-caption">故事在此落幕，其他选择仍在等你。</p><div className="ending-actions"><button type="button" className="primary-button" onClick={() => setPanel("branches")}><GitBranch size={18}/>查看分支</button><button type="button" className="secondary-button" onClick={() => node.parent_id && void selectNode(node.parent_id)} disabled={locked || !node.parent_id}>返回上一幕</button><button type="button" className="quiet-button" onClick={openSettings} disabled={locked}>开始新局 <ArrowRight size={16}/></button></div></> : <div className="action-grid">
            {scene.options.map((option, index) => <button type="button" className={`action-button ${index === 0 ? "primary-action" : ""}`} key={option.id} onClick={() => void choose({ type: "option", value: option.id })} disabled={locked}><span>{option.label}</span><ArrowRight size={19}/></button>)}
          </div>}
          {busy && <p className="action-status" role="status"><LoaderCircle size={16} className="spinner"/>{stage || "正在处理，请稍候"}</p>}
        </section>
      </div>
      {error && <div className="error-banner" role="alert"><p>{error}</p>{pending && <button type="button" className="secondary-button" disabled={busy} onClick={() => void initialize()}>重新连接任务</button>}</div>}
      <div className={`console-bottom ${terminal ? "is-terminal" : ""}`}>
        {!terminal && <form className="free-action" onSubmit={submit}><label htmlFor="free-action"><PencilLine size={20}/><span>自由行动</span></label><div className="compose-wrap"><div className="compose-field"><textarea id="free-action" value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} maxLength={500} rows={1} disabled={locked} placeholder="描述你想做的事……" aria-describedby="action-help"/><button type="submit" disabled={locked || !draft.trim()} className="send-button">{busy ? <LoaderCircle className="spinner" size={18}/> : "发送"}</button></div><div id="action-help" className="compose-help"><span>Ctrl / ⌘ + Enter 发送</span><span>{draft.length} / 500</span></div></div></form>}
        <nav className="utility-tools" aria-label="故事工具"><button type="button" onClick={() => setPanel("clues")}><BriefcaseBusiness size={21}/><span>线索</span>{clueCount > 0 && <span className="count-badge">{clueCount}</span>}</button><button type="button" onClick={() => setPanel("people")}><Users size={21}/><span>人物</span></button><button type="button" onClick={() => setPanel("branches")}><GitBranch size={21}/><span>记录</span></button></nav>
      </div>
    </main>

    {panel && <StoryPanel name={panel} onClose={() => setPanel(null)}>
      {panel === "people" && <PeoplePanel world={world}/>}
      {panel === "clues" && <CluesPanel node={node}/>}
      {panel === "history" && token && <HistoryPanel token={token} node={node} tree={tree} world={world}/>}
      {panel === "branches" && <BranchesPanel node={node} world={world} tree={tree} locked={locked} onSelect={id => { setPanel(null); void selectNode(id); }}/>}
      {panel === "story" && <div className="story-overview"><img src="/art/harbor.webp" alt="雨夜中的雾港候船厅"/><span className="eyebrow">{provider === "demo" ? "内置故事 · 无需密钥" : "当前故事"}</span><h3>{world.title}</h3><p>暴风雨封锁了雾港。一份失踪的航海日志，让三个人的命运交汇。</p><dl><div><dt>停留地点</dt><dd>{location?.name}</dd></div><div><dt>已保存</dt><dd>{tree.length} 幕</dd></div></dl><button className="primary-button wide-button" onClick={() => setPanel(null)}>继续游玩 <ArrowRight size={18}/></button><button className="secondary-button wide-button" disabled={locked} onClick={openSettings}>开始新故事</button><p className="panel-note">{provider === "demo" ? "Demo 使用预写剧情；所有选择与分支由本地服务保存。" : "当前故事的模型固定，已保存的内容可随时回看。"}本页保留当前会话，刷新后可继续。</p></div>}
      {panel === "reading" && <div className="reading-settings"><fieldset><legend>文字速度</legend><p className="panel-note">点击正文可立即显示当前句。</p><div className="speed-options">{([["instant", "即时"], ["normal", "标准"], ["slow", "慢速"]] as const).map(([value, label]) => <label key={value}><input type="radio" name="speed" value={value} checked={speed === value} onChange={() => saveReading(value, reduceMotion)}/><span>{label}</span></label>)}</div></fieldset><label className="motion-setting"><span><strong>减少动画</strong><small>直接显示完整文字，减少过渡效果</small></span><input type="checkbox" checked={reduceMotion} onChange={event => saveReading(speed, event.target.checked)}/></label>{systemReduced && <p className="panel-note">已遵循系统的减少动画设置。</p>}<p className="panel-note"><VolumeX size={16}/> 当前体验无音效，可安心阅读。</p></div>}
    </StoryPanel>}
    {settingsOpen && <LocalSettingsDialog currentProvider={provider} currentModel={modelId} hasProgress={tree.length > 1} onClose={() => setSettingsOpen(false)} onNewStory={newStory}/>}
  </div>;
}
