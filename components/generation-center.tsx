'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Session, WorkerRuntime } from '@/lib/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Progress } from '@/components/ui/progress';

type Source = { id: number; task: string; num_frames: number; session_id: string; episode_uuid: string };
type Attempt = { attempt_id: string; source_episode_uuid: string; object_xy_offset_m: number[] };
type Plan = { plan_id: string; total_attempts: number; plan: { nominal_only: boolean; attempts: Attempt[] } };
type Result = { attempt_id: string; status: string; error: string | null; episode_id: number | null; qa_status: string | null; offset_m: number[] };
type Job = { session: Session; worker: WorkerRuntime; plan_id: string; total: number; completed: number; succeeded: number; failed: number; gate_passed: boolean | null; report_status: string | null; results: Result[]; log_path: string };

export function GenerationCenter() {
  const [sources, setSources] = useState<Source[]>([]);
  const [unavailable, setUnavailable] = useState<{ id: number; reason: string }[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [mode, setMode] = useState('xy');
  const [count, setCount] = useState(20);
  const [range, setRange] = useState(.02);
  const [seed, setSeed] = useState(20260905);
  const [dataset, setDataset] = useState('robot_data_generated');
  const [gpu, setGpu] = useState(0);
  const [plan, setPlan] = useState<Plan>();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobId, setJobId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const job = jobs.find(item => item.session.id === jobId);
  const active = job && ['starting', 'running', 'stopping'].includes(job.worker.status);

  useEffect(() => {
    let cancelled = false;
    void api<{ items: Source[]; unavailable: { id: number; reason: string }[] }>('/generation/sources')
      .then(data => { if (!cancelled) { setSources(data.items); setUnavailable(data.unavailable); } })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    async function refresh() {
      try {
        const next = await api<Job[]>('/generation/jobs');
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

  function invalidate() { setPlan(undefined); setError(''); }
  async function preview() {
    setBusy(true); setError(''); setPlan(undefined); setNotice('');
    try { setPlan(await api<Plan>('/generation/plans', { method: 'POST', body: JSON.stringify({ episode_ids: selected, mode, attempts_per_source: count, range_m: range, seed }) })); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  async function start(planId: string, targetDataset: string, targetGpu: number) {
    setBusy(true); setError('');
    try {
      const next = await api<Job>(`/generation/plans/${planId}/start`, { method: 'POST', body: JSON.stringify({ dataset_name: targetDataset, gpu: targetGpu }) });
      setJobs(current => [next, ...current.filter(item => item.session.id !== next.session.id)]);
      setJobId(next.session.id); setPlan(undefined);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  async function action(name: 'stop' | 'scan') {
    if (!job) return;
    setBusy(true); setError('');
    try {
      const result = await api<{ indexed?: number; invalid?: number }>(`/generation/jobs/${job.session.id}/${name}`, { method: 'POST' });
      setNotice(name === 'scan' ? `扫描完成：新入库 ${result.indexed ?? 0}，无效 ${result.invalid ?? 0}。新 Episode 为待审核。` : '已请求停止；未完成的批次可继续执行。');
      setJobs(await api<Job[]>('/generation/jobs'));
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  return <div className="space-y-5">
    <div><h1 className="text-2xl font-semibold">数据生成 · 方块抬升</h1><p className="mt-2 text-sm text-muted-foreground">从已审核的人工示范制定计划，逐次运行真实仿真，再进入 Episode 审核与导出。</p></div>
    {error && <p role="alert" className="rounded border border-destructive p-3 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    <Card><CardHeader><CardTitle>1. 选择源示范</CardTitle></CardHeader><CardContent className="space-y-3">
      <p className="text-xs text-muted-foreground">只提供已 accepted、人工采集、自动任务成功且通过 generation 阶段校验的 Isaac rigid_cube_lift 示范。</p>
      <fieldset disabled={busy} className="max-h-72 space-y-2 overflow-auto">
        {sources.map(source => <label key={source.id} className="flex items-center gap-3 rounded border p-3 text-sm"><input type="checkbox" checked={selected.includes(source.id)} onChange={e => { setSelected(current => e.target.checked ? [...current, source.id] : current.filter(id => id !== source.id)); invalidate(); }} /><span>Episode #{source.id} · {source.num_frames} 帧 · {source.task}<small className="block break-all text-muted-foreground">{source.session_id}</small></span><a className="ml-auto shrink-0 text-primary" href={`/episodes/${source.id}`}>查看示范</a></label>)}
      </fieldset>
      {loading ? <p>正在校验源示范…</p> : !sources.length && <p>暂无符合条件的源示范；请先完成方块采集、扫描与 QA。</p>}
      {!!unavailable.length && <details><summary className="text-sm">不可用示范（{unavailable.length}）</summary>{unavailable.map(item => <p className="mt-2 text-xs" key={item.id}>#{item.id}：{item.reason}</p>)}</details>}
    </CardContent></Card>
    <Card><CardHeader><CardTitle>2. 配置与预览计划</CardTitle></CardHeader><CardContent className="space-y-4">
      <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-4">
        <label className="text-sm">生成模式<NativeSelect className="w-full" value={mode} onChange={e => { setMode(e.target.value); invalidate(); }}><NativeSelectOption value="nominal">零偏移重放</NativeSelectOption><NativeSelectOption value="xy">XY 扰动</NativeSelectOption></NativeSelect></label>
        <label className="text-sm">每条示范尝试次数<Input type="number" min={1} max={100} disabled={mode === 'nominal'} value={mode === 'nominal' ? 1 : count} onChange={e => { setCount(Number(e.target.value)); invalidate(); }} /></label>
        <label className="text-sm">XY 范围 ±（米）<Input type="number" min={.001} max={.1} step={.001} disabled={mode === 'nominal'} value={range} onChange={e => { setRange(Number(e.target.value)); invalidate(); }} /></label>
        <label className="text-sm">随机种子<Input type="number" min={0} step={1} value={seed} onChange={e => { setSeed(Number(e.target.value)); invalidate(); }} /></label>
      </fieldset>
      <Button disabled={busy || !selected.length} onClick={() => void preview()}>预览计划</Button>
      {plan && <div className="space-y-3 rounded border p-3"><p>已解析 {plan.total_attempts} 次尝试 · {plan.plan.nominal_only ? '全部重放成功才通过批次门槛' : '至少 50% 尝试成功才通过批次门槛'}</p><p className="text-xs text-muted-foreground">计划预览会保存参数快照，不启动 GPU。更改配置后请重新预览。默认保留抓取前收敛与抬升 8 cm 的既有门槛。</p><div className="max-h-72 overflow-auto"><table className="w-full text-left text-xs"><thead><tr><th>尝试</th><th>源 UUID</th><th>X / Y 偏移（米）</th></tr></thead><tbody>{plan.plan.attempts.slice(0,100).map(attempt => <tr key={attempt.attempt_id}><td className="py-2">{attempt.attempt_id}</td><td>{attempt.source_episode_uuid.slice(0,8)}</td><td>{attempt.object_xy_offset_m.map(x => x.toFixed(5)).join(' / ')}</td></tr>)}</tbody></table></div>{plan.total_attempts > 100 && <p className="text-xs">显示前 100 次尝试；完整计划见接口 JSON。</p>}</div>}
    </CardContent></Card>
    <Card><CardHeader><CardTitle>3. 启动批次</CardTitle></CardHeader><CardContent className="space-y-3"><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">输出 Dataset<Input value={dataset} disabled={busy} onChange={e => setDataset(e.target.value)} /></label><label className="text-sm">Worker GPU<Input type="number" min={0} max={255} value={gpu} disabled={busy} onChange={e => setGpu(Number(e.target.value))} /></label></div><p className="text-xs text-muted-foreground">PhysX · 无头执行 · 控制 20 Hz / 数据采样 10 Hz。与其他受管仿真共用资源锁。</p><Button disabled={busy || !plan || !dataset.trim()} onClick={() => plan && void start(plan.plan_id, dataset, gpu)}>启动预览的计划</Button></CardContent></Card>
    <Card><CardHeader><CardTitle>4. 进度与结果</CardTitle></CardHeader><CardContent className="space-y-4">
      <NativeSelect className="w-full" value={jobId} onChange={e => setJobId(e.target.value)}><NativeSelectOption value="">选择批次</NativeSelectOption>{jobs.map(item => <NativeSelectOption key={item.session.id} value={item.session.id}>{item.session.id} · {item.completed}/{item.total}</NativeSelectOption>)}</NativeSelect>
      {job && <><p>{job.report_status === 'completed' ? '批次执行完成' : job.worker.status} · 已完成 {job.completed}/{job.total} · 成功 {job.succeeded} · 失败 {job.failed}</p><Progress value={100 * job.completed / job.total} />{job.gate_passed !== null && <p>批次门槛：{job.gate_passed ? '通过' : '未通过'}。Episode QA 独立审核。</p>}{job.worker.error && <p role="alert" className="text-sm text-destructive">{job.worker.error}</p>}<div className="flex flex-wrap gap-3"><Button variant="destructive" disabled={busy || !active || job.worker.status === 'stopping'} onClick={() => void action('stop')}>停止批次</Button><Button variant="outline" disabled={busy || !!active || job.report_status === 'completed'} onClick={() => void start(job.plan_id, job.session.dataset_name!, Number(job.session.config.gpu))}>继续未完成批次</Button><Button variant="outline" disabled={busy || !!active} onClick={() => void action('scan')}>扫描结果入库</Button><a className="text-primary" href={`/sessions/${job.session.id}`}>会话与 Episode</a><a className="text-primary" href="/exports">导出中心</a></div><p className="break-all text-xs text-muted-foreground">Worker 日志：{job.log_path}</p><div className="max-h-96 overflow-auto"><table className="w-full text-left text-sm"><thead><tr><th>尝试</th><th>偏移（米）</th><th>物理结果 / 原因</th><th>Episode / QA</th></tr></thead><tbody>{job.results.map(result => <tr key={result.attempt_id}><td className="py-3">{result.attempt_id}</td><td>{result.offset_m.map(x => x.toFixed(4)).join(' / ')}</td><td>{result.status}{result.error && <small className="block text-destructive">{result.error}</small>}</td><td>{result.episode_id ? <a className="text-primary" href={`/episodes/${result.episode_id}`}>#{result.episode_id} · {result.qa_status}</a> : '尚未入库'}</td></tr>)}</tbody></table></div></>}
      {!jobs.length && <p className="text-sm text-muted-foreground">尚无生成批次。</p>}
    </CardContent></Card>
  </div>;
}
