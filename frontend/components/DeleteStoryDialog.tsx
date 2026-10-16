"use client";
import {useEffect,useRef,useState} from 'react';
import type {LibraryEntry} from '@/lib/library';

type Props={entry:LibraryEntry;onDelete:()=>Promise<void>;onClose:()=>void};

export function DeleteStoryDialog({entry,onDelete,onClose}:Props) {
  const dialogRef=useRef<HTMLDialogElement>(null),cancelRef=useRef<HTMLButtonElement>(null);
  const [error,setError]=useState(''),[deleting,setDeleting]=useState(false);
  const active=useRef(false);
  useEffect(()=>{
    const dialog=dialogRef.current,opener=document.activeElement;
    dialog?.showModal();cancelRef.current?.focus();
    return ()=>{
      if(dialog?.open)dialog.close();
      requestAnimationFrame(()=>{if(opener instanceof HTMLElement&&opener.isConnected)opener.focus();});
    };
  },[]);
  const confirm=async()=>{
    if(active.current)return;active.current=true;setDeleting(true);
    try {await onDelete();}
    catch {setError('删除未完成，故事库记录仍保留。请检查浏览器存储后重试。');active.current=false;setDeleting(false);}
  };
  return <dialog ref={dialogRef} className="settings-dialog delete-story-dialog" aria-labelledby="delete-story-title" aria-describedby="delete-story-description" onCancel={event=>{event.preventDefault();if(!active.current)onClose();}}>
    <div className="settings-heading"><h2 id="delete-story-title">删除游玩记录？</h2></div>
    <div className="settings-content">
      <p className="delete-story-name">《{entry.title}》</p>
      <p id="delete-story-description">将从本机故事库移除这局的进度、草稿和恢复凭据，删除后无法从故事库继续这局。服务端故事、图片和费用记录仍保留，样本与 Demo 可以重新开局。</p>
      {(entry.pending||!entry.nodeId)&&<p className="settings-help">删除不会取消已发出的生成任务。</p>}
      {error&&<p className="settings-error" role="alert">{error}</p>}
    </div>
    <div className="settings-footer delete-story-actions">
      <button ref={cancelRef} type="button" disabled={deleting} onClick={onClose}>取消</button>
      <button type="button" className="delete-story-confirm" disabled={deleting} onClick={()=>void confirm()}>{deleting?'正在删除…':'确认删除记录'}</button>
    </div>
  </dialog>;
}
