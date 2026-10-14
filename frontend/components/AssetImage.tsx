"use client";
import {useEffect,useState} from 'react';
import {api} from '@/lib/api';

const cache=new Map<string,string>();
export function useAssetImage(token:string|null,assetId?:string,retry=0) {
  const [src,setSrc]=useState<string|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    let active=true;setSrc(null);setError('');
    if (!token||!assetId) return;
    const key=`${token}:${assetId}`;
    const existing=cache.get(key);
    if (existing) {setSrc(existing);return;}
    void api.asset(token,assetId).then(blob=>{
      if (!active) return;
      const url=URL.createObjectURL(blob);cache.set(key,url);setSrc(url);
    }).catch(cause=>{if(active)setError((cause as Error).message);});
    return ()=>{active=false;};
  },[token,assetId,retry]);
  return {src,error};
}

export function AssetImage({token,assetId,alt,className}:{token:string;assetId:string;alt:string;className?:string}) {
  const {src,error}=useAssetImage(token,assetId);
  return src?<img src={src} alt={alt} className={className}/>:<span className={`asset-placeholder ${className||''}`} role="img" aria-label={error||`${alt}正在读取`}/>;
}
