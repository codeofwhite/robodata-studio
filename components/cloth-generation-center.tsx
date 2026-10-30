'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Progress } from '@/components/ui/progress';
import type { Appearance, AppearanceVariant, EnvironmentAppearance, PbrMaterial } from '@/lib/pbr-material-types';
import { originalEnvironment } from '@/lib/pbr-material-types';
import { CameraLightingControls } from './camera-lighting-controls';
import { originalCameraLighting, cameraLightingSummary, type CameraLightingRequest, type CameraLightingResolved } from '@/lib/camera-lighting-types';
import { SurfaceAppearanceControls } from './surface-appearance-controls';
import { AppearanceControls } from './garment-appearance-panel';
import type { Session, WorkerRuntime } from '@/lib/types';

type VisualVariant = AppearanceVariant & { camera_lighting?: CameraLightingRequest };
type Source = { id: number; task: string; num_frames: number; qa_status: string };
type Plan = { plan_id: string; total_attempts: number; plan: { attempts: { attempt_id: string; appearance: Appearance; environment?: EnvironmentAppearance; camera_lighting?: CameraLightingResolved }[] } };
type Job = { session: Session; worker: WorkerRuntime; plan_id: string; total: number; completed: number; succeeded: number; report_status: string | null; frame_progress: { stage: string; frame: number; total_frames: number } | null; results: { attempt_id: string; status: string; appearance: Appearance; environment?: EnvironmentAppearance; camera_lighting?: CameraLightingResolved; error: string | null; episode_id: number | null; qa_status: string | null }[] };

export function ClothGenerationCenter() {
  const [materials, setMaterials] = useState<PbrMaterial[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [unavailable, setUnavailable] = useState<{ id: number; reason: string }[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [appearances, setAppearances] = useState<VisualVariant[]>([{ texture: 'cotton', color: '#d95432', roughness: .85 }, { texture: 'denim', color: '#386ba1', roughness: .55 }]);
  const [plan, setPlan] = useState<Plan>();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobId, setJobId] = useState('');
  const [dataset, setDataset] = useState('cloth_appearance_generated');
  const [gpu, setGpu] = useState(2);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const job = jobs.find(item => item.session.id === jobId);
  const active = job && ['starting', 'running', 'stopping'].includes(job.worker.status);
  useEffect(() => {
    let cancelled = false;
    void api<{ items: PbrMaterial[] }>('/pbr-materials').then(result => { if (!cancelled) setMaterials(result.items); }).catch(e => { if (!cancelled) setError(String(e)); });
    void api<{ items: Source[]; unavailable: { id: number; reason: string }[] }>('/cloth-generation/sources').then(next => { if (!cancelled) { setSources(next.items); setUnavailable(next.unavailable); } }).catch(e => { if (!cancelled) setError(String(e)); }).finally(() => { if (!cancelled) setLoading(false); });
    async function refresh() {
      try {
        const next = await api<Job[]>('/cloth-generation/jobs');
        if (cancelled) return;
        setJobs(next);
        const requested = new URLSearchParams(window.location.search).get('session');
        setJobId(current => current || (next.some(item => item.session.id === requested) ? requested! : next[0]?.session.id ?? ''));
      } catch (e) { if (!cancelled) setError(String(e)); }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);
  function change(index: number, patch: Partial<VisualVariant>) {
    setAppearances(current => current.map((item, i) => i === index ? { ...item, ...patch } : item)); setPlan(undefined);
  }
  async function preview() {
    setBusy(true); setError(''); setPlan(undefined);
    try { setPlan(await api<Plan>('/cloth-generation/plans', { method: 'POST', body: JSON.stringify({ episode_ids: selected, appearances }) })); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  async function start(planId: string, name: string, device: number) {
    setBusy(true); setError('');
    try {
      const next = await api<Job>(`/cloth-generation/plans/${planId}/start`, { method: 'POST', body: JSON.stringify({ dataset_name: name, gpu: device }) });
      setJobs(current => [next, ...current.filter(item => item.session.id !== next.session.id)]); setJobId(next.session.id); setPlan(undefined);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  async function action(name: 'stop' | 'scan') {
    if (!job) return;
    setBusy(true); setError('');
    try {
      const result = await api<{ indexed?: number; invalid?: number }>(`/cloth-generation/jobs/${job.session.id}/${name}`, { method: 'POST' });
      setNotice(name === 'scan' ? `已入库 ${result.indexed ?? 0} 条，无效 ${result.invalid ?? 0} 条；新数据为待审核。` : '已请求停止，可继续未完成的外观。');
      setJobs(await api<Job[]>('/cloth-generation/jobs'));
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  return <div className="space-y-5">
    <div><h1 className="text-2xl font-semibold">衣物外观批量生成</h1><p className="mt-2 text-sm text-muted-foreground">复用已交付的 cuRobo 衣物动作和形变，更换外观后录制新图像。当前保留原场景；位置和物理参数变化尚未接入。</p></div>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <Card><CardHeader><CardTitle>1. 选择衣物源轨迹</CardTitle></CardHeader><CardContent className="space-y-3">
      {loading ? <p>正在读取源轨迹…</p> : !sources.length && <p>暂无已交付的成功衣物轨迹。</p>}
      {sources.map(source => <label key={source.id} className="flex items-center gap-3 rounded border p-3 text-sm"><input type="checkbox" disabled={busy} checked={selected.includes(source.id)} onChange={e => { setSelected(current => e.target.checked ? [...current, source.id] : current.filter(id => id !== source.id)); setPlan(undefined); }} /><span>Episode #{source.id} · {source.task} · {source.num_frames} 帧 · QA {source.qa_status}</span><a href={`/episodes/${source.id}`} className="ml-auto text-primary">查看</a></label>)}
      {!!unavailable.length && <details><summary>不可用的源轨迹（{unavailable.length}）</summary>{unavailable.map(item => <p key={item.id} className="text-xs">#{item.id}：{item.reason}</p>)}</details>}
      <p className="text-xs text-muted-foreground">源任务与交付验证已通过，源 QA 状态另行显示。局部夹持辅助及原任务指标会随生成数据保留；外观重渲染不会重新验证物理成功。</p>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>2. 外观组合与计划</CardTitle></CardHeader><CardContent className="space-y-4">
      {appearances.map((item, index) => <div key={index} className="space-y-3 rounded border p-3"><AppearanceControls value={item} onChange={next => change(index, next)} disabled={busy} options={{ appearance: item, materials, textures: [['none', '纯色'], ['cotton', '棉布'], ['linen', '亚麻'], ['denim', '牛仔'], ['terry', '毛巾']].map(([id, label]) => ({ id, label, artifact: null, thumbnail_url: id === 'none' ? null : '/assets/garment-textures/' + id })) }} /><SurfaceAppearanceControls value={item.environment ?? originalEnvironment} materials={materials} onChange={environment => change(index, { environment })} disabled={busy} /><CameraLightingControls value={item.camera_lighting ?? originalCameraLighting} onChange={camera_lighting => change(index, { camera_lighting })} disabled={busy} /><Button variant="outline" disabled={busy || appearances.length === 1} onClick={() => { setAppearances(current => current.filter((_, i) => i !== index)); setPlan(undefined); }}>移除</Button></div>)}
      <a className="text-primary" href="/assets?view=pbr">导入或浏览 PBR 材质库</a>
      <div className="flex gap-3"><Button variant="outline" disabled={busy || appearances.length >= 20} onClick={() => { setAppearances(current => [...current, { texture: 'none', color: '#386ba1', roughness: .9 }]); setPlan(undefined); }}>添加外观</Button><Button disabled={busy || !selected.length} onClick={() => void preview()}>预览计划</Button></div>
      {plan && <div className="space-y-2"><p>共 {plan.total_attempts} 条：每条源轨迹 × 每组外观，10 FPS 完整录制。</p>{plan.plan.attempts.map(attempt => <p className="text-xs" key={attempt.attempt_id}>{attempt.attempt_id} · {attempt.appearance.material_id ?? attempt.appearance.texture} · {attempt.appearance.color} · 粗糙度 {attempt.appearance.roughness} · 桌面 {attempt.environment?.tabletop?.material_id ?? (attempt.environment?.tabletop ? '纯色' : '原材质')} · 背景 {attempt.environment?.background?.material_id ?? (attempt.environment?.background ? '纯色' : '原材质')} · {cameraLightingSummary(attempt.camera_lighting)}</p>)}<div className="flex gap-3"><Input aria-label="输出数据集" value={dataset} onChange={e => setDataset(e.target.value)} /><Input aria-label="GPU" type="number" min={0} value={gpu} onChange={e => setGpu(Number(e.target.value))} /><Button disabled={busy} onClick={() => void start(plan.plan_id, dataset, gpu)}>启动</Button></div></div>}
    </CardContent></Card>
    <Card><CardHeader><CardTitle>3. 进度与结果</CardTitle></CardHeader><CardContent className="space-y-3">
      <NativeSelect value={jobId} onChange={e => setJobId(e.target.value)}><NativeSelectOption value="">选择批次</NativeSelectOption>{jobs.map(item => <NativeSelectOption key={item.session.id} value={item.session.id}>{item.session.id}</NativeSelectOption>)}</NativeSelect>
      {job && <><p>{job.worker.status} · 完成 {job.completed}/{job.total} · 成功 {job.succeeded} · 失败 {job.completed - job.succeeded}</p><Progress value={job.total ? job.completed / job.total * 100 : 0} />{active && job.frame_progress && <p className="text-sm">{job.frame_progress.stage === 'render' ? '渲染图像' : '保存 Episode'}：{job.frame_progress.frame}/{job.frame_progress.total_frames} 帧</p>}{job.worker.error && <p className="text-destructive">{job.worker.error}</p>}<div className="flex flex-wrap gap-3"><Button disabled={busy || !active} onClick={() => void action('stop')}>停止</Button><Button variant="outline" disabled={busy || Boolean(active) || job.report_status === 'completed'} onClick={() => void start(job.plan_id, job.session.dataset_name ?? dataset, Number(job.session.config?.gpu ?? gpu))}>继续</Button><Button disabled={busy || Boolean(active)} onClick={() => void action('scan')}>扫描结果入库</Button><a href={`/sessions/${job.session.id}`} className="text-primary">会话与日志</a><a href="/exports" className="text-primary">导出</a></div>{job.results.map(row => <div key={row.attempt_id} className="rounded border p-3 text-sm">{row.attempt_id} · {row.status} · {row.appearance.material_id ?? row.appearance.texture} · {row.appearance.color} · 桌面 {row.environment?.tabletop?.material_id ?? (row.environment?.tabletop ? '纯色' : '原材质')} · 背景 {row.environment?.background?.material_id ?? (row.environment?.background ? '纯色' : '原材质')} · {cameraLightingSummary(row.camera_lighting)}{row.error && <p className="text-destructive">{row.error}</p>}{row.episode_id ? <a className="ml-3 text-primary" href={`/episodes/${row.episode_id}`}>Episode #{row.episode_id} · {row.qa_status}</a> : <span className="ml-3">尚未入库</span>}</div>)}</>}
    </CardContent></Card>
  </div>;
}
