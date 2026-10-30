'use client';

import { useEffect, useState } from 'react';
import { Play } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { api, API_BASE } from '@/lib/api';
import { assetHref, outcomeLabel, type AssetRecord, type ClothRun, type Integrity, type ClothOptions, type AssetDetailResponse } from '@/lib/asset-types';

function GenesisClothRunPanel({ record, integrity }: { record: AssetRecord; integrity: Integrity }) {
  const [run, setRun] = useState<ClothRun>();
  const [error, setError] = useState('');
  const parameters = record.data.parameters as Record<string, unknown> | undefined;
  const supported = record.kind === 'config' && parameters?.id === 'textile_feeding' && parameters?.task === 'feed' && record.engines.includes('genesis');

  useEffect(() => {
    if (!run || (run.status !== 'queued' && run.status !== 'running')) return;
    const timer = window.setInterval(() => {
      void api<ClothRun>('/assets/runs/' + encodeURIComponent(run.run_id)).then(next => {
        setRun(next);
        if (next.status === 'completed' || next.status === 'failed') {
          window.setTimeout(() => { window.location.href = '/assets?focus=' + encodeURIComponent(record.asset_id); }, 1400);
        }
      }).catch(caught => setError(caught instanceof Error ? caught.message : '运行状态读取失败'));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [run?.run_id, run?.status, record.asset_id]);

  if (!supported) return null;
  async function start() {
    setError('');
    try {
      setRun(await api<ClothRun>('/assets/runs', { method: 'POST', body: JSON.stringify({ asset_id: record.asset_id, version: record.version }) }));
    } catch (caught) { setError(caught instanceof Error ? caught.message : '启动失败'); }
  }
  const active = run?.status === 'queued' || run?.status === 'running';
  return <Card className="border-primary/40"><CardHeader><CardTitle>从 Studio 运行 Genesis</CardTitle></CardHeader><CardContent className="space-y-3">
    <p className="text-sm text-muted-foreground">固定使用当前配置 v{record.version}。输出包含布料顶点、夹爪实际/目标位置、力、阶段、时间戳、评价和轨迹回放。</p>
    <p className="text-xs text-amber-400">当前执行器是笛卡尔双夹爪筛查，不代表 Franka 可达性，也不会直接标记为训练数据。</p>
    {!run && <Button disabled={integrity.status !== 'current'} onClick={() => void start()}><Play />启动运行</Button>}
    {run && <div className="space-y-2 rounded-lg border p-3"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono text-xs">{run.run_id}</span><Badge variant={run.status === 'failed' || run.outcome === 'failed' ? 'destructive' : 'outline'}>{active ? '运行中' : outcomeLabel(run.outcome)}</Badge></div><Progress value={Math.round(run.progress * 100)} /><p className="text-xs text-muted-foreground">{Math.round(run.progress * 100)}% · {run.status}</p>{run.error && <p className="text-xs text-destructive">{run.error}</p>}{run.log_tail && <pre className="max-h-52 overflow-auto whitespace-pre-wrap rounded bg-muted/40 p-2 text-[10px]">{run.log_tail}</pre>}{run.validation_asset_id && <a className="text-xs text-primary" href={assetHref(run.validation_asset_id, run.validation_version ?? undefined)}>查看自动登记的验证结果</a>}{!active && <p className="text-xs text-muted-foreground">即将返回验证概览，并定位当前配置……</p>}</div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </CardContent></Card>;
}

function NewtonClothRunPanel({ record, integrity }: { record: AssetRecord; integrity: Integrity }) {
  const [options, setOptions] = useState<ClothOptions>();
  const [material, setMaterial] = useState('medium');
  const [scenario, setScenario] = useState('hanging');
  const [values, setValues] = useState<Record<string, number>>({});
  const [solver, setSolver] = useState<Record<string, number>>({});
  const [run, setRun] = useState<ClothRun>();
  const [result, setResult] = useState<AssetDetailResponse>();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const storageKey = 'clothforge-run:' + record.asset_id + ':' + record.version;
  const active = starting || run?.status === 'queued' || run?.status === 'running';

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      let data = await api<ClothOptions>('/assets/' + encodeURIComponent(record.asset_id) + '/cloth-options?version=' + record.version, { signal: controller.signal });
      const previous = window.sessionStorage.getItem(storageKey);
      let restored: ClothRun | undefined;
      if (previous) {
        restored = await api<ClothRun>('/assets/runs/' + encodeURIComponent(previous), { signal: controller.signal });
        data = await api<ClothOptions>('/assets/' + encodeURIComponent(restored.config_asset_id) + '/cloth-options?version=' + restored.config_version, { signal: controller.signal });
      }
      if (controller.signal.aborted) return;
      setOptions(data); setMaterial(data.default_material); setScenario(data.default_scenario);
      const initial = data.initial_material ?? data.presets.find(p => p.id === data.default_material)!.parameters;
      setValues(Object.fromEntries(Object.keys(data.material_fields).map(key => [key, Number(initial[key])])));
      setSolver(data.initial_solver);
      setRun(restored);
    };
    void load().catch(caught => { if (!controller.signal.aborted) setError(String(caught)); });
    return () => controller.abort();
  }, [record.asset_id, record.version, storageKey]);

  useEffect(() => {
    if (!run || (run.status !== 'queued' && run.status !== 'running')) return;
    const timer = window.setInterval(() => {
      void api<ClothRun>('/assets/runs/' + encodeURIComponent(run.run_id)).then(setRun).catch(caught => setError(String(caught)));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [run?.run_id, run?.status]);

  useEffect(() => {
    if (!run?.validation_asset_id) return;
    void api<AssetDetailResponse>('/assets/' + encodeURIComponent(run.validation_asset_id) + '?version=' + run.validation_version).then(setResult).catch(caught => setError(String(caught)));
  }, [run?.validation_asset_id, run?.validation_version]);

  function chooseMaterial(id: string) {
    if (!options) return;
    const preset = options.presets.find(p => p.id === id)!;
    setMaterial(id); setValues(Object.fromEntries(Object.keys(options.material_fields).map(key => [key, Number(preset.parameters[key])])));
    setSolver(options.recommended_solvers[id][scenario]);
  }
  function chooseScenario(id: string) {
    setScenario(id);
    if (options) setSolver(options.recommended_solvers[material][id]);
  }
  async function start(event: React.FormEvent) {
    event.preventDefault(); setStarting(true); setError(''); setResult(undefined);
    try {
      const next = await api<ClothRun>('/assets/runs', { method: 'POST', body: JSON.stringify({
        asset_id: record.asset_id, version: record.version, scenario, material_id: material,
        material_overrides: values, solver_overrides: solver,
      }) });
      setRun(next); window.sessionStorage.setItem(storageKey, next.run_id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setStarting(false); }
  }
  const replay = result?.record.artifacts.findIndex(a => a.role === 'interactive_replay') ?? -1;
  const metrics = result?.record.data.metrics as Record<string, number> | undefined;
  const failures = result?.record.data.failed_gates as string[] | undefined;
  return <Card className="border-primary/40"><CardHeader><CardTitle>衣物仿真实验</CardTitle></CardHeader><CardContent className="space-y-5">
    <p className="text-sm text-muted-foreground">选择材料和场景，调整参数后运行 Newton。每次保存独立配置与真实轨迹，可在这里播放、旋转和对比结果。</p>
    {!options && !error && <p className="text-sm text-muted-foreground">正在加载衣物参数…</p>}
    {options && <form onSubmit={event => void start(event)} className="space-y-4">
      <fieldset disabled={active || integrity.status !== 'current'} className="space-y-4 disabled:opacity-60">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm">材料预设<NativeSelect aria-label="材料预设" className="w-full" value={material} onChange={event => chooseMaterial(event.target.value)}>{options.presets.map(p => <NativeSelectOption key={p.id} value={p.id}>{p.name}</NativeSelectOption>)}</NativeSelect></label>
          <label className="space-y-1 text-sm">试验场景<NativeSelect aria-label="试验场景" className="w-full" value={scenario} onChange={event => chooseScenario(event.target.value)}>{options.scenarios.map(s => <NativeSelectOption key={s.id} value={s.id}>{s.label}</NativeSelectOption>)}</NativeSelect></label>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{Object.entries(options.material_fields).map(([key, field]) => <label key={key} className="space-y-1 text-sm">{field.label}<Input aria-label={field.label} type="number" required min={field.min} max={field.max} step="any" value={values[key] ?? ''} onChange={event => setValues(previous => ({ ...previous, [key]: Number(event.target.value) }))} /><span className="text-xs text-muted-foreground">{field.unit}</span></label>)}</div>
        <details className="rounded-lg border p-3"><summary className="cursor-pointer text-sm">数值精度</summary><div className="mt-3 grid gap-3 sm:grid-cols-2">{Object.entries(options.solver_fields).map(([key, field]) => <label key={key} className="space-y-1 text-sm">{field.label}<NativeSelect aria-label={field.label} className="w-full" value={solver[key]} onChange={event => setSolver(previous => ({ ...previous, [key]: Number(event.target.value) }))}>{field.choices?.map(choice => <NativeSelectOption key={choice} value={choice}>{choice}</NativeSelectOption>)}</NativeSelect></label>)}</div><p className="mt-2 text-xs text-muted-foreground">切换材料或场景时恢复对应的推荐数值设置。</p></details>
      </fieldset>
      <p className="text-xs text-muted-foreground">合成材料，尚未实物标定。每次模拟 {options.duration_s} 秒；改变材料或数值参数后重新检查物理质量。</p>
      <Button type="submit" disabled={active || integrity.status !== 'current'}><Play />{active ? '运行中…' : run ? '用当前参数再运行' : '运行布料仿真'}</Button>
    </form>}
    {run && <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm">{active ? 'Newton 正在计算实际布料轨迹' : '本次运行结果'}</span><Badge variant={run.status === 'failed' || run.outcome === 'failed' ? 'destructive' : 'outline'}>{active ? '运行中' : outcomeLabel(run.outcome)}</Badge></div>
      <Progress value={Math.round(run.progress * 100)} />
      <p className="text-xs text-muted-foreground">{Math.round(run.progress * 100)}% · {run.status}</p>
      {run.error && <p role="alert" className="text-sm text-destructive">{run.error}</p>}
      {metrics && <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
        <div>最大伸长<strong className="block font-mono">{metrics.maximum_principal_stretch == null ? '—' : ((metrics.maximum_principal_stretch - 1) * 100).toFixed(2) + '%'}</strong></div>
        <div>最大穿地<strong className="block font-mono">{metrics.maximum_ground_penetration_m == null ? '—' : (metrics.maximum_ground_penetration_m * 1000).toFixed(3) + ' mm'}</strong></div>
        <div>保存帧自交<strong className="block font-mono">{metrics.maximum_self_intersection_pairs ?? '—'}</strong></div>
      </div>}
      {!!failures?.length && <p className="text-sm text-destructive">未通过：{failures.join('、')}</p>}
      {replay >= 0 && result?.integrity.status === 'current' && <iframe title="布料仿真回放" className="h-[540px] w-full rounded-lg border bg-slate-950" sandbox="allow-scripts" src={API_BASE + '/assets/' + encodeURIComponent(result.record.asset_id) + '/versions/' + result.record.version + '/artifacts/' + replay + '/viewer'} />}
      <div className="flex flex-wrap gap-4 text-xs"><a className="text-primary" href={assetHref(run.config_asset_id, run.config_version)}>本次参数快照</a>{run.validation_asset_id && <a className="text-primary" href={assetHref(run.validation_asset_id, run.validation_version ?? undefined)}>完整指标与下载</a>}</div>
      {run.log_tail && <details><summary className="cursor-pointer text-xs text-muted-foreground">运行日志</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-muted/40 p-2 text-[10px]">{run.log_tail}</pre></details>}
    </div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </CardContent></Card>;
}

export function ClothRunPanel(props: { record: AssetRecord; integrity: Integrity }) {
  if (props.record.tags.includes('clothforge') && props.record.engines.includes('newton_vbd') && ['model', 'config'].includes(props.record.kind)) return <NewtonClothRunPanel key={props.record.asset_id + ':' + props.record.version} {...props} />;
  return <GenesisClothRunPanel {...props} />;
}
