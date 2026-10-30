'use client';
import {useEffect,useState} from 'react';
import {api,API_BASE} from '@/lib/api';
import type {ClothCatalog} from '@/lib/cloth-types';
import {ClothSolverComparison} from './cloth-solver-comparison';
export function ClothTaskCenter(){
 const [data,setData]=useState<ClothCatalog>();const [error,setError]=useState('');const [notice,setNotice]=useState('');const [busy,setBusy]=useState(false);const [filter,setFilter]=useState('all');const [tab,setTab]=useState('tasks');
 async function load(){try{setData(await api<ClothCatalog>('/cloth/tasks'));}catch(e){setError(String(e));}}
 useEffect(()=>{void load();},[]);
 async function ingest(){setBusy(true);setError('');try{const r=await api<{indexed:number;skipped:number;errors:unknown[]}>('/cloth/import',{method:'POST',body:JSON.stringify({dry_run:false})});setNotice(`新增 ${r.indexed} 条，已存在 ${r.skipped} 条。新记录保持待审核。`);if(r.errors.length)setError(JSON.stringify(r.errors));await load();}catch(e){setError(String(e));}finally{setBusy(false);}}
 const taskGroups=new Map<string,{name:string;versions:ClothCatalog['tasks']}>();
 for(const version of data?.tasks??[]){
  const group=taskGroups.get(version.task);
  if(group)group.versions.push(version);
  else taskGroups.set(version.task,{name:version.name,versions:[version]});
 }
 return <div className="space-y-6"><div><h1 className="text-2xl font-semibold">布料任务中心</h1><p className="mt-2 text-sm text-muted-foreground">查看已有操作成果、管理训练数据，比较同一衣物的不同物理后端。</p></div>
 <div className="flex flex-wrap gap-3"><button className="rounded border px-4 py-2" onClick={()=>setTab('tasks')} aria-pressed={tab==='tasks'}>操作成果与数据</button><button className="rounded border px-4 py-2" onClick={()=>setTab('compare')} aria-pressed={tab==='compare'}>跨求解器比较</button><a className="rounded border px-4 py-2" href="/assets?view=cloth">衣物调参工作台</a></div>
 {tab==='compare'?<ClothSolverComparison/>:<><div className="flex flex-wrap items-center gap-3"><strong>已交付 {data?.summary.delivered??'—'} · 已入库 {data?.summary.indexed??'—'}</strong><button className="rounded bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50" disabled={busy} onClick={()=>void ingest()}>{busy?'校验并入库中…':'校验并入库已交付示范'}</button><button className="rounded border px-3 py-2" onClick={()=>void load()}>刷新</button><a href="/episodes" className="text-primary">Episode 审核</a><a href="/exports" className="text-primary">导出中心</a></div>
 <p className="text-sm text-muted-foreground">这些机器人示范使用局部辅助夹持。任务成功、完整交付、训练 QA 分开记录；原始数据只读。机器人任务复跑入口尚未开放，当前提供回放与入库。</p>
 <label className="block">操作类别 <select className="ml-2 rounded border bg-background p-2" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">全部任务</option>{Array.from(new Map(data?.tasks.map(t=>[t.task,t.name])).entries()).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>
 {notice&&<p role="status">{notice}</p>}{error&&<p role="alert" className="text-destructive">{error}</p>}{data?.issues.map(x=><p key={x.batch} role="alert">{x.batch}: {x.error}</p>)}
 <div className="grid items-start gap-4 xl:grid-cols-2">
 {Array.from(taskGroups.entries()).filter(([task])=>filter==='all'||filter===task).map(([task,group])=>
  <details className="rounded-xl border p-4" key={task}>
   <summary className="cursor-pointer font-semibold">{group.name}</summary>
   <div className="mt-3 space-y-3">
   {[...group.versions].sort((a,b)=>a.variant.localeCompare(b.variant,undefined,{numeric:true})).map(t=>{
    const delivered=t.attempts.filter(a=>a.delivery_passed);
    const a=delivered.at(-1)??t.attempts.at(-1);
    const poster=a?.media.find(p=>p.role==='preview')?.url;
    const status=!a?'未尝试':a.delivery_passed?'成功':a.numeric_success?'物理通过，交付待完成':a.numeric_success===false||a.error?'失败':'未完成';
    return <details className="rounded-lg border p-3" key={t.batch+':'+t.variant}>
     <summary className="cursor-pointer text-sm"><span className="font-medium">{t.variant}</span><span className="ml-3 text-muted-foreground">{status}</span></summary>
     <div className="mt-3">
      <p className="my-2 text-sm">物理 {a?.numeric_success===true?'通过':a?.numeric_success===false?'失败':'未判定'} · 交付 {a?.delivery_passed?'通过':'未完成'} · 辅助夹持</p>
      {a?.media.filter(m=>m.role==='video').slice(0,2).map(m=><figure key={m.path}><figcaption className="mb-1 text-xs text-muted-foreground">{m.label==='video_overview_4x'?'概览 · 4 倍速':m.label==='video_front'?'正视回放':m.label}</figcaption><video className="mb-2 w-full rounded bg-black" controls preload="none" poster={poster?API_BASE+poster:undefined} src={API_BASE+m.url}/></figure>)}
      <div className="flex flex-wrap gap-3 text-sm">{a?.asset_id&&<a className="text-primary" href={'/assets/'+encodeURIComponent(a.asset_id)}>资产与轨迹</a>}{a?.episodes.map(e=><span key={e.uuid}>{e.id?<a className="text-primary" href={'/episodes/'+e.id}>Episode #{e.id}</a>:'尚未入库'} · {e.qa_status==='pending'?'待审核':e.qa_status} · {e.fps} Hz</span>)}</div>
      <details className="mt-3"><summary className="cursor-pointer">全部尝试与失败原因（{t.attempts.length}）</summary>{t.attempts.map(r=><div className="mt-2 break-all border-t pt-2 text-xs" key={r.run_id}><p>{r.run_id}</p><p>{r.status} · 物理 {r.numeric_success===true?'通过':r.numeric_success===false?'失败':'未判定'} · 交付 {r.delivery_passed?'通过':'未完成'}</p><p>{r.error??r.failed_gates?.join('、')}</p></div>)}</details>
     </div>
    </details>;
   })}
   </div>
  </details>
 )}
 </div></>}

 </div>;
}
