"use client";
import {useEffect,useRef,useState} from 'react';
import {ArrowRight,BookOpen,Plus,Settings,Clock3,GitBranch} from 'lucide-react';
import {api} from '@/lib/api';
import {migrateLegacy,readLibrary,saveEntry} from '@/lib/library';
import type {LibraryEntry} from '@/lib/library';
import {beginLocalSample} from '@/lib/localSamples';
import type {LocalSample} from '@/lib/types';
import {LocalSettingsDialog} from './LocalSettingsDialog';
import {AssetImage} from './AssetImage';

export default function Library() {
  const [entries,setEntries]=useState<LibraryEntry[]>([]),[error,setError]=useState('');
  const [settings,setSettings]=useState(false),[busy,setBusy]=useState(false);
  const active=useRef(false);
  const [samples,setSamples]=useState<LocalSample[]>([]);
  useEffect(()=>{void api.localSamples().then(result=>setSamples(result.samples)).catch(cause=>setError('本地样本暂时无法读取：'+(cause as Error).message));},[]);
  const startSample=async(sample:Pick<LocalSample,'id'|'title'>,existing?:LibraryEntry)=>{
    if(active.current)return;active.current=true;setBusy(true);setError('');
    try {const entry=await beginLocalSample(sample,existing);window.location.href=`/play?id=${entry.id}`;}
    catch(cause){setEntries(readLibrary().entries);setError((cause as Error).message);setBusy(false);active.current=false;}
  };
  useEffect(()=>{try{setEntries(migrateLegacy().entries);}catch(cause){setError((cause as Error).message);}},[]);
  const demo=async()=>{
    if(active.current)return;active.current=true;setBusy(true);setError('');
    try {
      const created=await api.createSession();
      const entry=saveEntry({id:crypto.randomUUID(),token:created.token,kind:'legacy',title:'雾港最后一夜',provider:'demo',
        modelId:'demo',nodeId:created.root.id,draft:'',updatedAt:new Date().toISOString()});
      window.location.href=`/play?id=${entry.id}`;
    }catch(cause){setError((cause as Error).message);setBusy(false);active.current=false;}
  };
  return <div className="library-page">
    <header className="journey-header"><a href="/" className="brand"><BookOpen size={22}/>即兴剧场</a><button className="quiet-button" onClick={()=>setSettings(true)}><Settings size={19}/>本地设置</button></header>
    <main>
      <section className="library-hero"><img src="/art/harbor.webp" alt="雨夜里的雾港候船厅"/><div className="hero-copy"><span className="eyebrow">你的故事库</span><h1>每个选择，<br/>都留下一条路。</h1><p>回到未完的故事，或写下新的起点。</p><a className="primary-button" href="/create"><Plus size={18}/>创建新故事</a></div></section>
      {error&&<p className="error-banner" role="alert">{error}</p>}
      <section className="shelf"><div className="shelf-heading"><div><h2>继续你的旅程</h2><p>每一局的进度与分支都会单独保留。</p></div><span>{entries.length} 段故事</span></div>
        {!entries.length?<div className="library-empty"><GitBranch size={30}/><h3>第一段故事，在等你。</h3><p>先试试无需密钥的 Demo，或创建属于你的调查故事。</p></div>:<div className="story-cards">{[...entries].reverse().map(entry=><a className="story-card" key={entry.id} onClick={event=>{if(entry.sampleId&&!entry.coverAssetId){event.preventDefault();void startSample({id:entry.sampleId,title:entry.title},entry);}}} href={`${entry.kind==='custom'&&!entry.sampleId&&!entry.coverAssetId?'/create':'/play'}?id=${entry.id}`}>
          <div className="card-cover">{entry.coverAssetId?<AssetImage token={entry.token} assetId={entry.coverAssetId} alt={entry.title}/>:entry.kind==='legacy'?<img src="/art/harbor.webp" alt="雾港候船厅"/>:<div className="card-pending"><Clock3 size={30}/><span>正在准备故事</span></div>}</div>
          <div className="card-copy"><span className="eyebrow">{entry.sampleId?'本地样本 · 无需密钥':entry.kind==='legacy'?'内置故事':'自定义故事'}</span><h3>{entry.title}</h3><p>{entry.pending?'有待恢复的行动':entry.sampleId&&!entry.coverAssetId?'恢复本地样本':entry.kind==='custom'&&!entry.coverAssetId?'继续创建与准备':'已保存，随时继续'}</p><span className="card-action">继续故事<ArrowRight size={17}/></span></div>
        </a>)}</div>}
      </section>
      {samples.length>0&&<section className="shelf"><div className="shelf-heading"><div><h2>本地样本 · 无需密钥</h2><p>用按钮调查与探索三个结局。每次开始都会保存独立进度。</p></div></div><div className="story-cards">{samples.map(sample=><article className="story-card" key={sample.id}><div className="card-copy"><span className="eyebrow">{{ancient:'古代',modern:'近现代',future:'未来'}[sample.era]} · 固定故事与配图</span><h3>{sample.title}</h3><p>{sample.intro}</p><button className="secondary-button" disabled={busy} onClick={()=>void startSample(sample)}>开始试玩<ArrowRight size={18}/></button></div></article>)}</div></section>}
      <section className="demo-invitation"><div><span className="eyebrow">内置 Demo · 无需密钥</span><h2>雾港最后一夜</h2><p>暴风雨、航海日志，以及三个不同的结局。</p></div><button className="secondary-button" disabled={busy} onClick={()=>void demo()}>开始 Demo<ArrowRight size={18}/></button></section>
    </main>
    <footer className="journey-footer">故事保存在这台设备与本地服务中。API Key 只在后端内存中保留。</footer>
    {settings&&<LocalSettingsDialog currentProvider="demo" currentModel="demo" hasProgress={false} onClose={()=>setSettings(false)} onNewStory={async provider=>{if(provider==='demo')await demo();else window.location.href='/create';}}/>}
  </div>;
}
