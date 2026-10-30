'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { assetHref, type AssetList, type AssetRecord } from '@/lib/asset-types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export const clothCategoryLabels: Record<string, string> = {
  tshirt: '短袖上衣', trousers: '长裤', open_coat: '开襟外套', towel: '毛巾',
  napkin: '餐巾', long_sleeve: '长袖上衣', shorts: '短裤', skirt: '半身裙',
};
type Attempt = { asset_id: string; version: number; name: string; status: string; outcome?: string; run_id: string | null; error?: string; validation_asset_id?: string; config_asset_id?: string };
type Plan = { plan_id: string; status: string; total: number; completed: number; succeeded: number; gpu: number; error: string | null; attempts: Attempt[] };
type Props = { assets?: AssetRecord[]; selected?: string[]; onSelectionChange?: (ids: string[]) => void };

export function ClothforgeBatchPanel({ assets, selected, onSelectionChange }: Props) {
  const [loaded, setLoaded] = useState<AssetRecord[]>([]);
  const [localSelection, setLocalSelection] = useState<string[]>([]);
  const [scenario, setScenario] = useState('hanging');
  const [material, setMaterial] = useState('medium');
  const [overrides, setOverrides] = useState<Record<string, number>>({});
  const [plan, setPlan] = useState<Plan>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const choices = assets ?? loaded;
  const selection = selected ?? localSelection;
  const active = plan?.status === 'running';
  useEffect(() => { setPlan(current => current?.status === 'preview' ? undefined : current); }, [selection.join(',')]);
  useEffect(() => {
    if (assets) return;
    let cancelled = false;
    void api<AssetList>('/assets?q=clothforge&kind=model&limit=250').then(r => { if (!cancelled) setLoaded(r.items); }).catch(e => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [assets]);
  useEffect(() => {
    const id = localStorage.getItem('clothforge-batch-plan');
    if (id) void api<Plan>('/clothforge-batches/plans/' + id).then(setPlan).catch(e => setError(String(e)));
  }, []);
  useEffect(() => {
    if (!active || !plan) return;
    const id = plan.plan_id;
    const timer = setInterval(() => { void api<Plan>('/clothforge-batches/plans/' + id).then(setPlan).catch(e => setError(String(e))); }, 2000);
    return () => clearInterval(timer);
  }, [active, plan?.plan_id]);
  function choose(ids: string[]) { (onSelectionChange ?? setLocalSelection)(ids); setPlan(undefined); }
  async function preview() {
    setBusy(true); setError('');
    try {
      const next = await api<Plan>('/clothforge-batches/plans', { method: 'POST', body: JSON.stringify({
        garments: choices.filter(a => selection.includes(a.asset_id)).map(a => ({ asset_id: a.asset_id, version: a.version })),
        scenario, material_id: material, material_overrides: overrides,
      }) });
      setPlan(next); localStorage.setItem('clothforge-batch-plan', next.plan_id);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  async function start() {
    if (!plan) return;
    setBusy(true); setError('');
    try { setPlan(await api<Plan>('/clothforge-batches/plans/' + plan.plan_id + '/start', { method: 'POST' })); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  return <details className="rounded-xl border p-4" id="clothforge-batch">
    <summary className="cursor-pointer font-medium">ClothForge 批量运行<span className="ml-3 text-xs text-muted-foreground">{active ? `运行中 · ${plan.completed}/${plan.total}` : `已选 ${selection.length} 件`}</span></summary>
    <div className="mt-4 space-y-4">
      <p className="text-xs text-muted-foreground">逐件运行 Newton 悬挂／落地，保存参数和真实布料轨迹。机器人操作在衣物详情的工位入口进行。</p>
      <fieldset disabled={busy || active} className="space-y-3 disabled:opacity-60">
        {!assets && <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{Object.entries(clothCategoryLabels).map(([category, label]) => {
          const items = choices.filter(a => a.data.category === category);
          return <details className="rounded border p-2" key={category}><summary className="cursor-pointer text-sm">{label} · {items.length}</summary><div className="mt-2 space-y-1"><label className="flex gap-2 text-xs"><input type="checkbox" checked={items.length > 0 && items.every(a => selection.includes(a.asset_id))} onChange={e => choose(e.target.checked ? Array.from(new Set([...selection, ...items.map(a => a.asset_id)])) : selection.filter(id => !items.some(a => a.asset_id === id)))} />选择此类</label>{items.map(a => <label className="flex gap-2 text-xs" key={a.asset_id}><input type="checkbox" checked={selection.includes(a.asset_id)} onChange={e => choose(e.target.checked ? [...selection, a.asset_id] : selection.filter(id => id !== a.asset_id))} />{a.name}</label>)}</div></details>;
        })}</div>}
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label>场景 <select aria-label="批量场景" className="rounded border bg-background p-1" value={scenario} onChange={e => { setScenario(e.target.value); setPlan(undefined); }}><option value="hanging">悬挂</option><option value="drop">落地</option></select></label>
          <label>材料 <select aria-label="批量材料" className="rounded border bg-background p-1" value={material} onChange={e => { setMaterial(e.target.value); setOverrides({}); setPlan(undefined); }}><option value="light">轻薄</option><option value="medium">中等</option><option value="heavy">厚实</option></select></label>
          <Button size="sm" onClick={() => void preview()} disabled={!selection.length}>预览计划（{selection.length} 件）</Button>
        </div>
        <details className="rounded border p-2"><summary className="cursor-pointer text-xs">自定义物理参数</summary><div className="mt-2 grid gap-2 sm:grid-cols-3">{[['mass_per_area', '面密度 kg/m²'], ['friction', '摩擦系数'], ['tri_ke', '拉伸刚度'], ['tri_ka', '面积刚度'], ['edge_ke', '弯曲刚度']].map(([key, label]) => <label className="text-xs" key={key}>{label}<Input aria-label={'批量' + label} type="number" step="any" value={overrides[key] ?? ''} placeholder="使用材料预设" onChange={e => { setOverrides(old => { const next = { ...old }; if (e.target.value === '') delete next[key]; else next[key] = Number(e.target.value); return next; }); setPlan(undefined); }} /></label>)}</div></details>
      </fieldset>
      {plan && <div className="space-y-2 rounded border p-3 text-sm">
        <div className="flex flex-wrap items-center gap-3"><span>{plan.status === 'preview' ? '计划已准备' : plan.status === 'running' ? '运行中' : '批次结束'} · {plan.total} 件 · GPU {plan.gpu}</span>{plan.status === 'preview' && <Button size="sm" disabled={busy} onClick={() => void start()}>启动批量</Button>}</div>
        {plan.status !== 'preview' && <p>已完成 {plan.completed}/{plan.total} · 物理通过 {plan.succeeded}</p>}
        <details><summary className="cursor-pointer text-xs">{plan.status === 'preview' ? '查看计划明细' : '查看逐件结果'}</summary><div className="mt-2 max-h-72 space-y-2 overflow-auto">{plan.attempts.map((a, i) => <div className="flex flex-wrap gap-3 border-t pt-2 text-xs" key={i}><a className="text-primary" href={assetHref(a.asset_id, a.version)}>{a.name}</a><span>{a.status === 'pending' ? '待运行' : a.status === 'running' || a.status === 'queued' ? '运行中' : a.outcome === 'passed' ? '通过' : '失败'}</span>{a.config_asset_id && <a className="text-primary" href={assetHref(a.config_asset_id)}>参数</a>}{a.validation_asset_id && <a className="text-primary" href={assetHref(a.validation_asset_id)}>轨迹与结果</a>}{a.error && <span className="text-destructive">{a.error}</span>}</div>)}</div></details>
        {plan.error && <p role="alert">{plan.error}</p>}
      </div>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  </details>;
}
