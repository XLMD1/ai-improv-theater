"use client";
import {useEffect,useRef,useState,type FormEvent} from 'react';
import {ArrowLeft,ArrowRight,Check,ImageIcon,LoaderCircle,Settings} from 'lucide-react';
import {api} from '@/lib/api';
import {beginCreation,prepareImages,resumeCreation} from '@/lib/creation';
import {findEntry,updateEntry} from '@/lib/library';
import type {CreationRequest,LibraryEntry} from '@/lib/library';
import type {CreationTask,ImageTask,LocalSettings} from '@/lib/types';
import {LocalSettingsDialog} from './LocalSettingsDialog';

const stages:Record<string,string>={generate:'生成故事设定',content_generate:'生成故事设定',repair:'修复设定',reachability:'检查调查路径',semantic:'核查证据与真相',semantic_check:'核查证据与真相',awaiting_confirmation:'等待你确认'};
const errors:Record<string,string>={key_not_configured:'尚未配置所需密钥，请打开本地设置。',unauthorized:'供应商拒绝了密钥，请在设置中重新检查。',
  budget_exhausted:'共享预算已达到上限，暂停新的模型调用。',cost_unconfirmed:'有调用结果或费用未确认，需先在本地核账。',
  image_outcome_unconfirmed:'图片请求结果未确认。请先核账并找回原输出，不能直接再次请求。',outcome_unknown:'请求发出后结果未确认，已保留进度和费用预留。',
  download_rejected:'图片已生成，但下载未完成。恢复时会使用原图片链接。',invalid_image:'图片未通过尺寸或格式检查，原设定和已完成素材均保留。',
  connect_failure:'网络连接暂时失败。已保留进度，可稍后恢复。',process_restarted:'服务已重启，已保存的设定和素材保留，可恢复未完成部分。'};
const message=(cause:unknown)=>cause instanceof TypeError?'无法连接本地服务。输入和请求已保留，恢复服务后可继续。':errors[(cause as Error).message]||(cause as Error).message;

export default function CreateStory() {
  const [entry,setEntry]=useState<LibraryEntry|null>(null),[loaded,setLoaded]=useState(false);
  const [setting,setSetting]=useState(''),[era,setEra]=useState<CreationRequest['era']>('modern');
  const [task,setTask]=useState<CreationTask|null>(null),[images,setImages]=useState<ImageTask|null>(null);
  const [config,setConfig]=useState<LocalSettings|null>(null),[settings,setSettings]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[refresh,setRefresh]=useState(0),[missingConfirmed,setMissingConfirmed]=useState(false);
  const activeRequest=useRef(false);
  useEffect(()=>{
    try {
      const id=new URLSearchParams(window.location.search).get('id')||undefined;
      const saved=id?findEntry(id):undefined;
      if(id&&!saved)throw new Error('本机未找到该故事，请返回故事库。');
      if(saved){setEntry(saved);setSetting(saved.createRequest?.setting||'');setEra(saved.createRequest?.era||'modern');}
    }catch(cause){setError(message(cause));}
    setLoaded(true);
  },[]);
  useEffect(()=>{void api.settings().then(setConfig).catch(cause=>setError(message(cause)));},[settings,refresh]);
  useEffect(()=>{
    if(!entry?.id)return;
    let running=true,timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try{
        const saved=findEntry(entry!.id)!;
        if(saved.imageTaskId){
          const current=await api.imageTask(saved.token,saved.imageTaskId);if(!running)return;setImages(current);
          if(current.status==='ready'&&current.completed===current.total){
            const [assets,node]=await Promise.all([api.assets(saved.token),api.node(saved.token,saved.nodeId!)]);
            if(running)setEntry(updateEntry(saved.id,{coverAssetId:assets.backgrounds[node.scene_id]}));
            return;
          }
          if(!['queued','running'].includes(current.status))return;
        }else if(saved.nodeId){
          const manifest=await api.assets(saved.token);if(!running)return;
          if(manifest.task_id){setEntry(updateEntry(saved.id,{imageTaskId:manifest.task_id}));return;}
          return;
        }else if(saved.creationTaskId){
          const current=await api.creationTask(saved.token,saved.creationTaskId);if(!running)return;setTask(current);
          if(current.title){setEntry(updateEntry(saved.id,{title:current.title}));}
          if(current.status==='approved'){
            const session=await api.currentSession(saved.token);
            if(running&&session.root_node_id)setEntry(updateEntry(saved.id,{nodeId:session.root_node_id}));
            return;
          }
          if(current.status==='declined'){
            setEntry(updateEntry(saved.id,{creationTaskId:undefined,createKey:undefined,createRequest:undefined}));setTask(null);return;
          }
          if(!['queued','running'].includes(current.status))return;
        }else return;
        if(running)timer=setTimeout(()=>void poll(),1000);
      }catch(cause){if(running)setError(message(cause));}
    }
    void poll();return()=>{running=false;clearTimeout(timer);};
  },[entry?.id,entry?.creationTaskId,entry?.imageTaskId,entry?.nodeId,refresh]);
  const perform=async(work:()=>Promise<void>)=>{
    if(activeRequest.current)return;activeRequest.current=true;setBusy(true);setError('');
    try{await work();setRefresh(value=>value+1);}catch(cause){setError(message(cause));
      const id=entry?.id||new URLSearchParams(window.location.search).get('id');if(id)setEntry(findEntry(id)||null);
    }finally{activeRequest.current=false;setBusy(false);}
  };
  const submit=(event:FormEvent)=>{event.preventDefault();void perform(async()=>{
    if(!setting.trim()||setting.length>500)return;
    // The helper persists credentials/request/key synchronously before any HTTP.
    const promise=beginCreation({setting:setting.trim(),era},entry||undefined);
    const saved=findEntry();if(saved){setEntry(saved);window.history.replaceState(null,'',`/create?id=${saved.id}`);}
    setEntry(await promise);
  });};
  const confirm=()=>perform(async()=>{
    if(!entry||!task?.candidate_version_id||!task.content_hash)return;
    const result=await api.confirmTask(entry.token,task.id,task.candidate_version_id,task.content_hash);
    setEntry(updateEntry(entry.id,{nodeId:result.root.id,title:task.title||entry.title}));
  });
  const reject=()=>perform(async()=>{
    if(!entry||!task)return;await api.rejectTask(entry.token,task.id);
    setEntry(updateEntry(entry.id,{creationTaskId:undefined,createKey:undefined,createRequest:undefined}));setTask(null);
  });
  const preparing=Boolean(entry?.nodeId),hasTask=Boolean(entry?.creationTaskId),pendingRequest=Boolean(entry?.createKey&&!hasTask);
  const imagesReady=images?.status==='ready'&&images.completed===images.total;
  const settingsDialog=settings&&<LocalSettingsDialog currentProvider="deepseek" currentModel="deepseek-flash" hasProgress={false} onClose={()=>setSettings(false)} onNewStory={async provider=>{window.location.href=provider==='demo'?'/':'/create';}}/>;
  return <div className="journey-page"><header className="journey-header"><a href="/" className="quiet-button"><ArrowLeft size={20}/>故事库</a><span>即兴剧场</span><button className="quiet-button" onClick={()=>setSettings(true)}><Settings size={19}/>本地设置</button></header>
    <main className="creation-layout"><aside className="creation-context"><span className="eyebrow">新的调查故事</span><h1>{preparing?'让故事，\n有了模样。':hasTask?'一段故事，\n正在成形。':'写下故事的起点。'}</h1><p>你给出背景与年代。固定的真相、人物与调查路径，将在确认后保存。</p><ol className="journey-steps"><li className={!hasTask&&!preparing?'current':''}>背景与年代</li><li className={hasTask&&!preparing?'current':''}>生成与确认设定</li><li className={preparing?'current':''}>准备场景与人物</li><li>进入故事</li></ol><p className="panel-note">三位人物 · 五个地点 · 三种结局<br/>设定与已保存的剧情不会因回放改变。</p></aside>
      <section className="creation-form-card">
        {!loaded?<p role="status">正在恢复故事……</p>:preparing?<>
          <span className="eyebrow">场景与人物准备</span><h2>{entry?.title}</h2><p>所有图片固定保存后，再进入故事。恢复只补未完成部分。</p>
          {images?<><div className="preparation-count"><strong>{images.completed}<small> / {images.total}</small></strong><span>已完成</span></div><progress value={images.completed} max={images.total} aria-label="图片完成数量"/><div className="asset-slots">{images.assets.map(asset=><div className={asset.available?'ready':''} key={asset.id}>{asset.available?<Check size={17}/>:<ImageIcon size={17}/>}<span>{asset.name}</span><small>{asset.available?'已保存':asset.status==='generating'?'生成中':asset.status==='download_pending'?'待下载':asset.status==='uncertain'?'结果未确认':'待完成'}</small></div>)}</div>
            {images.error_code&&<p className="error-banner" role="alert">{errors[images.error_code]||'配图未完成。已保留设定与成功素材，请检查设置后恢复。'}</p>}
            {images.error_code&&<button className="quiet-button" onClick={()=>setRefresh(value=>value+1)}>重新核对状态</button>}
            {images.requires_missing_output_confirmation&&<label className="missing-confirm"><input type="checkbox" checked={missingConfirmed} onChange={event=>setMissingConfirmed(event.target.checked)}/>已完成本地费用核账，并确认无法找回原图片输出。重新请求可能再次计费。</label>}
          </>:<div className="preparation-intro"><ImageIcon size={36}/><p>即将准备五张背景和三张人物图。</p><p className="panel-note">CogView-4 · standard · 完整一套 ¥0.48<br/>共享预算：80 元提醒，100 元停止新调用。</p></div>}
          {imagesReady?<a className="primary-button wide-button" href={`/play?id=${entry!.id}`}>进入故事<ArrowRight size={18}/></a>:<button className="primary-button wide-button" disabled={busy||images?.status==='running'||images?.status==='queued'||(images?.requires_missing_output_confirmation&&(!images.recoverable||!missingConfirmed))||(!config?.providers.cogview.configured&&(!images||images.needs_generation))} onClick={()=>void perform(async()=>{setEntry(await prepareImages(findEntry(entry!.id)!,missingConfirmed));})}>{busy?<LoaderCircle size={18} className="spinner"/>:<ImageIcon size={18}/>} {images?'恢复未完成素材':'开始准备图片'}</button>}
          {!config?.providers.cogview.configured&&(!images||images.needs_generation)&&<p className="panel-note">请在本地设置中配置智谱密钥。已保存的素材会直接复用。</p>}
        </>:hasTask?<>
          <span className="eyebrow">故事设定</span><h2>{task?.title||'正在生成你的故事'}</h2>
          {task?.status==='awaiting_confirmation'?<><p className="candidate-intro">{task.public_intro}</p><div className="candidate-detail"><strong>{task.protagonist?.name}</strong><p>{task.protagonist?.appearance}</p><strong>{task.location?.name}</strong><p>{task.location?.description}</p></div><p className="panel-note">这里只呈现无剧透简介。确认后设定固定，开始准备配图。</p><div className="journey-actions"><button className="secondary-button" disabled={busy} onClick={()=>void reject()}>返回修改背景</button><button className="primary-button" disabled={busy} onClick={()=>void confirm()}>确认设定<ArrowRight size={18}/></button></div></>:task&&['failed','interrupted'].includes(task.status)?<><p className="error-banner" role="alert">{errors[task.error_code||'']||'故事设定未能完成，输入与检查点已保留。'}</p><button className="primary-button" disabled={busy||!task.recoverable} onClick={()=>void perform(async()=>{setEntry(await resumeCreation(findEntry(entry!.id)!));})}>恢复创建</button>{!task.recoverable&&<p className="panel-note">本次设定已用完修复机会。可返回故事库创建新的故事，原任务保留。</p>}</>:<div className="creation-progress" role="status"><LoaderCircle className="spinner" size={30}/><h3>{stages[task?.stage||'']||'服务端正在处理设定'}</h3><p>校验完成前不会显示候选正文。</p></div>}
        </>:<form onSubmit={submit}><span className="eyebrow">背景与年代</span><h2>让悬念从这里开始。</h2><label htmlFor="story-setting">故事背景</label><textarea id="story-setting" value={setting} maxLength={500} required rows={5} disabled={busy||pendingRequest} onChange={event=>setSetting(event.target.value)} placeholder="例如：古代运河边的城镇，一艘运船失踪，三位知情人在封锁的码头相遇……"/><p className="input-count">{setting.length} / 500</p><fieldset disabled={busy||pendingRequest}><legend>故事年代</legend><div className="era-options">{([['ancient','古代'],['modern','近现代'],['future','未来']] as const).map(([value,label])=><label className={era===value?'selected':''} key={value}><input type="radio" name="era" value={value} checked={era===value} onChange={()=>setEra(value)}/>{label}</label>)}</div></fieldset><p className="panel-note">文字模型：DeepSeek Flash。文字按实际用量估算；确认设定后配图，完整八张图片 ¥0.48。</p><button className="primary-button wide-button" type="submit" disabled={busy||!setting.trim()||!config?.providers.deepseek.configured||config.budget.status==='blocked'}>{busy?<LoaderCircle className="spinner" size={18}/>:<ArrowRight size={18}/>} {pendingRequest?'重连原创建请求':'生成故事设定'}</button>{!config?.providers.deepseek.configured&&<p className="panel-note">请先在本地设置中配置 DeepSeek 密钥。</p>}</form>}
        {error&&<div className="error-banner" role="alert"><p>{error}</p><button className="secondary-button" disabled={busy} onClick={()=>{setError('');setRefresh(value=>value+1);}}>重新读取进度</button></div>}
      </section>
    </main>{settingsDialog}
  </div>;
}
