import type { CharacterId } from "@/lib/types";

const palettes: Record<string, [string, string, string]> = {
  s1: ["#122c38", "#315967", "#d4a660"],
  s2: ["#1c2833", "#45525b", "#d1a76c"],
  s3: ["#102b37", "#346079", "#e0a56f"],
  s4: ["#1c2637", "#5a4c64", "#e4b17a"],
  s5: ["#102937", "#4d6c71", "#f1c77d"],
  e1: ["#294356", "#a9716f", "#ffdaa0"],
  e2: ["#314e57", "#b28872", "#ffe2ad"],
  e3: ["#253d51", "#716b7b", "#dfbca5"],
};

export function SceneArt({ sceneId }: { sceneId: string }) {
  const [dark, middle, glow] = palettes[sceneId] || palettes.s1;
  const archive = sceneId === "s2";
  const tower = sceneId === "s4";
  const lighthouse = sceneId === "s5" || sceneId.startsWith("e");
  return (
    <svg className="scene-art" viewBox="0 0 1200 620" role="img" aria-label={`雾港${archive ? "档案室" : tower ? "钟楼" : lighthouse ? "灯塔" : "海港"}场景插画`} preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id="sky" x2="0" y2="1"><stop stopColor={dark}/><stop offset="1" stopColor={middle}/></linearGradient>
        <radialGradient id="light"><stop stopColor={glow} stopOpacity=".7"/><stop offset="1" stopColor={glow} stopOpacity="0"/></radialGradient>
        <linearGradient id="sea" x2="0" y2="1"><stop stopColor="#2d5662"/><stop offset="1" stopColor="#0b202b"/></linearGradient>
      </defs>
      <rect width="1200" height="620" fill="url(#sky)"/>
      <circle cx={lighthouse ? 885 : 760} cy={lighthouse ? 155 : 190} r="235" fill="url(#light)"/>
      {!archive && <>
        <path d="M0 350 Q230 320 410 345 T810 338 T1200 347 V620 H0Z" fill="url(#sea)"/>
        <path d="M0 412 Q200 396 400 416 T800 410 T1200 430" stroke="#b5d1d1" strokeOpacity=".18" fill="none" strokeWidth="3"/>
        <path d="M0 482 Q250 458 480 485 T950 475 T1200 492" stroke="#b5d1d1" strokeOpacity=".13" fill="none" strokeWidth="4"/>
      </>}
      {archive ? <>
        <path d="M0 0H1200V620H0Z" fill="#0b1720" fillOpacity=".28"/>
        {[30, 330, 870, 1130].map(x => <g key={x}>
          <rect x={x} y="25" width="210" height="540" fill="#172631" stroke="#9e7b54" strokeOpacity=".5" strokeWidth="5"/>
          {[115, 235, 355, 475].map(y => <g key={y}>
            <path d={`M${x + 7} ${y}h195`} stroke="#b79668" strokeWidth="7"/>
            {[0, 1, 2, 3, 4, 5].map(i => <rect key={i} x={x + 15 + i * 31} y={y - 84} width={24 + (i % 2) * 4} height="82" fill={i % 2 ? "#8b664e" : "#65736e"} opacity=".75"/>)}</g>)}
        </g>)}
        <path d="M510 0V620M690 0V620" stroke="#bd9e72" strokeOpacity=".35" strokeWidth="8"/>
        <path d="M510 0H690V620H510Z" fill="#c6b184" fillOpacity=".05"/>
      </> : tower ? <>
        <path d="M110 340V130l70-50 70 50v210M950 340V115l60-45 60 45v225" fill="#172734"/>
        <path d="M410 364V85h310v279" fill="#172632" stroke="#63717b" strokeWidth="6"/>
        <path d="M465 87l100-65 100 65" fill="none" stroke="#877c79" strokeWidth="18"/>
        <circle cx="565" cy="180" r="68" fill="#d5bd8a" opacity=".75"/>
        <circle cx="565" cy="180" r="56" fill="#293949"/>
        <path d="M565 136v47l31 28" stroke="#e7d4a8" strokeWidth="7" fill="none" strokeLinecap="round"/>
        <path d="M0 355H1200V620H0Z" fill="#0e1d29" fillOpacity=".72"/>
      </> : lighthouse ? <>
        <path d="M700 360L760 80h110l65 280" fill="#d3bd9a" opacity=".82"/>
        <path d="M745 160h144M725 258h187" stroke="#8f6f68" strokeWidth="16"/>
        <path d="M747 75h132l-22-37h-88Z" fill="#273341"/>
        <rect x="782" y="85" width="56" height="45" fill={glow}/>
        <path d="M800 114L0 310V0H1200V0L824 130Z" fill={glow} opacity=".09"/>
        <path d="M0 428Q300 360 550 405T1200 392V620H0Z" fill="#142b36"/>
      </> : <>
        <path d="M55 354V185h175v169M300 355V235h160v120M960 355V166h170v189" fill="#172c37"/>
        <path d="M70 200h145M970 180h142" stroke="#ccae83" strokeOpacity=".5" strokeWidth="8"/>
        <path d="M520 340L610 245 700 340M605 250V110" stroke="#b7c5be" strokeWidth="5" fill="none"/>
        <path d="M605 118l84 90H605Z" fill="#bed0c8" opacity=".35"/>
        <path d="M0 420h1200" stroke="#caad7a" strokeOpacity=".25" strokeWidth="5"/>
        <path d="M0 520L360 410h480l360 110" fill="#142633" opacity=".9"/>
      </>}
      <rect width="1200" height="620" fill="#07131d" opacity=".12"/>
    </svg>
  );
}
const portraitColors: Record<CharacterId, { hair: string; coat: string; skin: string; accent: string }> = {
  c1: { hair: "#17252b", coat: "#9f6b59", skin: "#efc6a8", accent: "#d7ac75" },
  c2: { hair: "#242b2e", coat: "#426473", skin: "#dfb797", accent: "#b8d4d6" },
  c3: { hair: "#342d33", coat: "#7d6d8c", skin: "#f1c9ab", accent: "#e4b985" },
};

export function CharacterPortrait({ id, name }: { id: CharacterId; name: string }) {
  const p = portraitColors[id];
  return (
    <svg className="portrait" viewBox="0 0 250 330" role="img" aria-label={`${name}的立绘`}>
      <ellipse cx="125" cy="315" rx="115" ry="28" fill="#081720" opacity=".38"/>
      <path d="M36 330Q41 218 90 204h70q49 14 54 126Z" fill={p.coat}/>
      <path d="M87 210l38 53 39-53" fill={p.accent}/>
      <path d="M111 188h28v39h-28Z" fill={p.skin}/>
      <ellipse cx="125" cy="123" rx="62" ry="83" fill={p.hair}/>
      <ellipse cx="125" cy="135" rx="47" ry="65" fill={p.skin}/>
      <path d="M77 110Q70 50 113 39q58-7 64 70-20-23-38-30-20 24-62 31Z" fill={p.hair}/>
      <path d="M94 132q12-7 22 0M137 132q12-7 22 0" stroke="#493835" strokeWidth="3" fill="none" strokeLinecap="round"/>
      <path d="M112 171q13 9 26 0" stroke="#9a655d" strokeWidth="3" fill="none" strokeLinecap="round"/>
      <path d="M121 140l-4 17h11" stroke="#bd927e" strokeWidth="2" fill="none"/>
      {id === "c1" && <path d="M48 330l25-86 18-13-6 99M202 330l-25-86-18-13 6 99" fill="#bb8068"/>}
      {id === "c2" && <path d="M90 211l35 52 35-52 28 21-63 85-63-85Z" fill="#263f4c"/>}
      {id === "c3" && <path d="M85 215l40 42 40-42M63 233l-14 97M187 233l14 97" stroke="#b69aac" strokeWidth="10" fill="none"/>}
    </svg>
  );
}
