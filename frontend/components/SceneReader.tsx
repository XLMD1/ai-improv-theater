"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Maximize2, Minimize2 } from "lucide-react";
import { readingLines } from "@/lib/reading";
import type { RenderedScene, World } from "@/lib/types";

export type ReadingSpeed = "instant" | "normal" | "slow";

export function SceneReader({ scene, world, speed, reducedMotion }: {
  scene: RenderedScene; world: World; speed: ReadingSpeed; reducedMotion: boolean;
}) {
  const lines = useMemo(() => readingLines(scene), [scene]);
  const [index, setIndex] = useState(0);
  const [count, setCount] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const line = lines[index];
  const text = line?.text || "";
  const instant = reducedMotion || speed === "instant";
  const complete = instant || count >= text.length;
  const people: Record<string, { name: string }> = world.characters;

  useEffect(() => {
    if (instant || expanded) return;
    const timer = window.setInterval(() => setCount(value => Math.min(value + (speed === "slow" ? 1 : 2), text.length)), speed === "slow" ? 65 : 32);
    return () => window.clearInterval(timer);
  }, [text, instant, speed, expanded]);

  const move = (next: number) => { setIndex(next); setCount(0); };
  return <div className={`scene-reader ${expanded ? "is-expanded" : ""}`}>
    {expanded ? <div className="full-scene">
      <p>{scene.narration}</p>
      {scene.dialogue.map((dialogue, i) => <div className="saved-dialogue" key={i}><strong>{people[dialogue.character_id]?.name || "人物"}</strong><p>{dialogue.text}</p></div>)}
    </div> : <>
      {line?.characterId && <span className="speaker-name">{people[line.characterId]?.name || "人物"}</span>}
      <button className="sentence" type="button" onClick={() => !complete ? setCount(text.length) : index < lines.length - 1 && move(index + 1)} aria-label={`${text} ${!complete ? "点击显示完整句子" : index < lines.length - 1 ? "点击阅读下一句" : "本幕已读完"}`}>
        <span aria-hidden="true">{instant ? text : text.slice(0, count)}{!complete && <span className="reading-cursor"/>}</span>
      </button>
    </>}
    <div className="reading-controls">
      <button type="button" className="quiet-button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded}>
        {expanded ? <Minimize2 size={15}/> : <Maximize2 size={15}/>} {expanded ? "逐句阅读" : "展开本幕"}
      </button>
      {!expanded && <div className="sentence-navigation">
        <button type="button" aria-label="上一句" disabled={index === 0} onClick={() => move(index - 1)}><ChevronLeft size={17}/></button>
        <span aria-live="polite">{index + 1} / {lines.length || 1}</span>
        <button type="button" aria-label={!complete ? "显示完整句子" : "下一句"} disabled={complete && index === lines.length - 1} onClick={() => !complete ? setCount(text.length) : move(index + 1)}><ChevronRight size={17}/></button>
      </div>}
    </div>
  </div>;
}
