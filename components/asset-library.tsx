'use client';

import { useEffect, useState } from 'react';
import { Boxes, Plus, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ClothforgeBatchPanel, clothCategoryLabels } from '@/components/clothforge-batch-panel';
import { PbrMaterialLibrary } from '@/components/pbr-material-library';
import { ValidationOverview } from '@/components/validation-overview';
import { AssetEditor } from '@/components/asset-detail';
import { ClothGarmentPicker, previewAppearance } from './cloth-garment-picker';
import { ClothGarmentPreview } from './cloth-garment-preview';
import type { PbrMaterial } from '@/lib/pbr-material-types';
import { api } from '@/lib/api';
import { assetHref, kindLabels, outcomeLabel, type AssetKind, type AssetList } from '@/lib/asset-types';

export function AssetLibrary() {
  const [view, setView] = useState<'overview' | 'index' | 'cloth' | 'pbr'>('overview');
  const [q, setQ] = useState('');
  const [kind, setKind] = useState('');
  const [engine, setEngine] = useState('');
  const [outcome, setOutcome] = useState('');
  const [integrity, setIntegrity] = useState('');
  const [offset, setOffset] = useState(0);
  const [showScanRecords, setShowScanRecords] = useState(false);
  const [tick, setTick] = useState(0);
  const [data, setData] = useState<AssetList>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const limit = 30;
  useEffect(() => { const requested = new URLSearchParams(window.location.search).get('view'); if (requested === 'cloth' || requested === 'pbr') setView(requested); }, []);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      // config/validation 是 ClothForge 扫描的日志，属于「验证概览」；默认不混进资产索引
      const kindQuery = kind || (showScanRecords ? '' : 'model,scene,material');
      const query = new URLSearchParams({ q, kind: kindQuery, engine, outcome, integrity, offset: String(offset), limit: String(limit) });
      void api<AssetList>('/assets?' + query, { signal: controller.signal }).then(result => {
        if (!controller.signal.aborted) { setData(result); setError(''); }
      }).catch(caught => {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : '加载失败');
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [q, kind, engine, outcome, integrity, offset, tick, showScanRecords]);

  return <div className="space-y-5">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><Badge variant="outline" className="mb-3">ASSET REGISTRY</Badge><h1 className="text-2xl font-semibold">资产与材料</h1><p className="mt-2 text-sm text-muted-foreground">按固定编号查找资产，追溯每个版本的配置、模型与验证证据。</p></div>
      <div className="flex gap-2"><Button variant="outline" onClick={() => setTick(tick + 1)}><RefreshCw className={loading ? 'animate-spin' : ''} />刷新</Button><Button onClick={() => setCreating(!creating)}><Plus />登记资产</Button></div>
    </div>
    {creating && <AssetEditor onCancel={() => setCreating(false)} />}
    <div className="flex flex-wrap gap-2" aria-label="资产页面视图"><Button variant={view === 'pbr' ? 'default' : 'outline'} onClick={() => setView('pbr')}>PBR 材质</Button><Button variant={view === 'cloth' ? 'default' : 'outline'} aria-pressed={view === 'cloth'} onClick={() => setView('cloth')}>衣物仿真</Button><Button variant={view === 'overview' ? 'default' : 'outline'} aria-pressed={view === 'overview'} onClick={() => setView('overview')}>验证概览</Button><Button variant={view === 'index' ? 'default' : 'outline'} aria-pressed={view === 'index'} onClick={() => setView('index')}>资产索引</Button></div>
    {view === 'pbr' ? <PbrMaterialLibrary /> : view === 'cloth' ? <ClothGallery refresh={tick} /> : view === 'overview' ? <ValidationOverview refresh={tick} /> : <>
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      {(Object.keys(kindLabels) as AssetKind[]).map(key => <button key={key} className={'rounded-xl border p-4 text-left transition-colors ' + (kind === key ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted/50')} onClick={() => { setKind(kind === key ? '' : key); setOffset(0); }}><span className="block text-sm text-muted-foreground">{kindLabels[key]}</span><strong className="mt-2 block font-mono text-2xl">{data?.counts[key] ?? '—'}</strong></button>)}
    </div>
    {error && <div role="alert" className="rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{error}</div>}
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><Boxes className="size-4" />资产索引</CardTitle>
        <div className="grid gap-2 pt-3 md:grid-cols-2 xl:grid-cols-5">
          <label className="relative"><Search className="absolute left-3 top-3 size-4 text-muted-foreground" /><Input aria-label="搜索资产名称或编号" className="pl-9" placeholder="名称、编号、标签…" value={q} onChange={e => { setQ(e.target.value); setOffset(0); }} /></label>
          <NativeSelect aria-label="资产类型" value={kind} onChange={e => { setKind(e.target.value); setOffset(0); }}><NativeSelectOption value="">全部类型</NativeSelectOption>{Object.entries(kindLabels).map(([key, label]) => <NativeSelectOption key={key} value={key}>{label}</NativeSelectOption>)}</NativeSelect>
          <NativeSelect aria-label="仿真引擎" value={engine} onChange={e => { setEngine(e.target.value); setOffset(0); }}><NativeSelectOption value="">全部引擎</NativeSelectOption>{['genesis', 'isaac_sim', 'newton_vbd', 'newton', 'roboverse'].map(key => <NativeSelectOption key={key} value={key}>{key}</NativeSelectOption>)}</NativeSelect>
          <NativeSelect aria-label="验证结果" value={outcome} onChange={e => { setOutcome(e.target.value); setOffset(0); }}><NativeSelectOption value="">全部记录结果</NativeSelectOption><NativeSelectOption value="passed">通过</NativeSelectOption><NativeSelectOption value="failed">失败</NativeSelectOption><NativeSelectOption value="unavailable">未判定</NativeSelectOption></NativeSelect>
          <NativeSelect aria-label="证据完整性" value={integrity} onChange={e => { setIntegrity(e.target.value); setOffset(0); }}><NativeSelectOption value="">全部证据状态</NativeSelectOption><NativeSelectOption value="current">引用文件一致</NativeSelectOption><NativeSelectOption value="stale">证据过期 / 缺失</NativeSelectOption></NativeSelect>
        </div>
      </CardHeader>
      <CardContent><div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">{loading ? '正在核对版本与文件…' : '匹配 ' + (data?.total ?? 0) + ' 项'} · 默认显示各资产最新版本，历史版本在详情中查看。文件一致不等于物理验证通过。</p>
          <Button size="sm" variant={showScanRecords ? 'default' : 'outline'} aria-pressed={showScanRecords} onClick={() => { setShowScanRecords(!showScanRecords); setOffset(0); }}>{showScanRecords ? '隐藏扫描记录' : '显示扫描记录'}</Button>
        </div>
        <Table><TableHeader><TableRow><TableHead>资产 / 固定编号</TableHead><TableHead>类型</TableHead><TableHead>版本</TableHead><TableHead>引擎</TableHead><TableHead>记录结果</TableHead><TableHead>证据</TableHead></TableRow></TableHeader><TableBody>
          {!loading && !data?.items.length && <TableRow><TableCell colSpan={6} className="py-12 text-center text-muted-foreground">没有匹配资产，可调整筛选或登记新资产。</TableCell></TableRow>}
          {data?.items.map(record => <TableRow key={record.asset_id}><TableCell><a className="font-medium text-primary hover:underline" href={assetHref(record.asset_id)}>{record.name}</a><p className="mt-1 break-all font-mono text-xs text-muted-foreground">{record.asset_id}</p></TableCell><TableCell>{kindLabels[record.kind]}</TableCell><TableCell className="font-mono">v{record.version}</TableCell><TableCell className="text-xs">{record.engines.join(' · ') || '通用'}</TableCell><TableCell><Badge variant={record.data.outcome === 'failed' ? 'destructive' : 'outline'}>{outcomeLabel(record.data.outcome)}</Badge></TableCell><TableCell><Badge variant={record.integrity.status === 'stale' ? 'destructive' : 'outline'}>{record.integrity.status === 'current' ? '文件一致' : '证据过期'}</Badge></TableCell></TableRow>)}
        </TableBody></Table>
        <div className="mt-4 flex items-center justify-between"><span className="text-xs text-muted-foreground">{data?.revision_count ?? 0} 个已保存版本</span><div className="flex items-center gap-3"><Button variant="outline" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - limit))}>上一页</Button><span className="text-xs">{Math.floor(offset / limit) + 1}</span><Button variant="outline" disabled={loading || offset + limit >= (data?.total ?? 0)} onClick={() => setOffset(offset + limit)}>下一页</Button></div></div>
      </CardContent>
    </Card>
    </>}
  </div>;
}


function ClothGallery({ refresh }: { refresh: number }) {
  const [data, setData] = useState<AssetList>();
  const [error, setError] = useState('');
  const [category, setCategory] = useState('');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [materials, setMaterials] = useState<PbrMaterial[]>([]);
  const [openCategory, setOpenCategory] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void api<AssetList>('/assets?q=clothforge&kind=model&engine=newton_vbd&limit=250', { signal: controller.signal }).then(setData).catch(caught => { if (!controller.signal.aborted) setError(String(caught)); });
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    let cancelled = false;
    void api<{ items: PbrMaterial[] }>('/pbr-materials').then(result => { if (!cancelled) setMaterials(result.items.filter(m => (m.data.category ?? 'fabric') === 'fabric')); }).catch(e => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, []);
  const items = (data?.items ?? []).filter(item => (!category || item.data.category === category) && (!query || (item.name + ' ' + item.asset_id).toLowerCase().includes(query.toLowerCase())));
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">衣物库</h2><p className="mt-1 text-xs text-muted-foreground">按类别展开尺寸变体，预览、调参并进入双臂工位。</p></div><div className="flex gap-2"><Input aria-label="搜索衣物" placeholder="名称或编号" value={query} onChange={e => setQuery(e.target.value)} /><NativeSelect aria-label="衣物类别" value={category} onChange={event => setCategory(event.target.value)}><NativeSelectOption value="">全部类别</NativeSelectOption>{Object.entries(clothCategoryLabels).map(([id, label]) => <NativeSelectOption key={id} value={id}>{label}</NativeSelectOption>)}</NativeSelect></div></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!data && !error && <p className="text-sm text-muted-foreground">正在加载衣物…</p>}
    <div className="grid items-start gap-3 sm:grid-cols-2 xl:grid-cols-4">{Object.entries(clothCategoryLabels).map(([id, label]) => {
      const variants = items.filter(a => a.data.category === id).sort((a,b) => a.name.localeCompare(b.name, undefined, {numeric:true}));
      if (!variants.length) return null;
      const first = variants[0];
      const appearance = previewAppearance(first, materials[0]);
      const material = materials.find(m => m.asset_id === appearance.material_id && m.version === appearance.material_version);
      const open = openCategory === id;
      return <details className={'rounded-xl border p-3 ' + (open ? 'sm:col-span-2' : '')} key={id} data-cloth-category={id} open={open}>
        <summary className="cursor-pointer list-none text-sm font-medium" onClick={e => { e.preventDefault(); setOpenCategory(open ? '' : id); }}>
          <span>{open ? '▾' : '▸'} {label}<span className="ml-2 text-xs font-normal text-muted-foreground">{variants.length} 件</span></span>
          {materials.length > 0 && <div className="mt-2"><ClothGarmentPreview record={first} appearance={appearance} material={material} thumbnail /></div>}
        </summary>
        {open && <ClothGarmentPicker key={id} variants={variants} materials={materials} selected={selected} onSelectionChange={setSelected} />}
      </details>;
    })}</div>
    {data && <p className="text-xs text-muted-foreground">共 {data.total} 件 · 当前匹配 {items.length} 件 · 点击类别展开，点击衣物查看三维预览和调参。</p>}
    <ClothforgeBatchPanel assets={data?.items} selected={selected} onSelectionChange={setSelected} />
  </div>;
}
