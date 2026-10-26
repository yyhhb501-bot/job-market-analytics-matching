"use client";
import {useEffect} from "react";
import {useRouter} from "next/navigation";

export function RefreshCollection(){
  const router=useRouter();
  useEffect(()=>{
    const refresh=()=>{if(document.visibilityState==="visible") router.refresh();};
    const timer=setInterval(refresh,30000);
    document.addEventListener("visibilitychange",refresh);
    return ()=>{clearInterval(timer);document.removeEventListener("visibilitychange",refresh);};
  },[router]);
  return <p className="small"><button type="button" className="btn-secondary" onClick={()=>router.refresh()}>刷新数据</button>{" "}页面可见时每 30 秒自动更新；历史回执会保留原完成时间。</p>;
}
