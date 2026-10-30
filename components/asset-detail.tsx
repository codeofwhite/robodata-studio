'use client';

import { useEffect, useState, type FormEvent } from 'react';
import { ArrowLeft, Download, GitBranch } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { api, API_BASE, bytes } from '@/lib/api';
import { assetHref, kindLabels, prefixes, outcomeLabel, type AssetDraft, type AssetKind, type AssetRecord, type AssetDetailResponse, type Artifact } from '@/lib/asset-types';
import { ClothRunPanel } from '@/components/cloth-run-panel';
import { GarmentAppearancePanel } from '@/components/garment-appearance-panel';

const pretty = (value: unknown) => JSON.stringify(value, null, 2);

export function AssetEditor({ initial, onCancel }: { initial?: AssetRecord; onCancel: () => void }) {
  const [kind, setKind] = useState<AssetKind>(initial?.kind ?? 'material');
  const [assetId, setAssetId] = useState(initial?.asset_id ?? '');
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [tags, setTags] = useState(initial?.tags.join(', ') ?? '');
  const [engines, setEngines] = useState(initial?.engines.join(', ') ?? '');
  const [data, setData] = useState(pretty(initial?.data ?? { calibrated: false, parameters: {} }));
  const [references, setReferences] = useState(pretty(initial?.references ?? []));
  const [artifacts, setArtifacts] = useState(pretty(initial?.artifacts ?? []));
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState('cloth-batch-v1');
  const [filePath, setFilePath] = useState('');
  const [role, setRole] = useState('source');

  async function addArtifact() {
    setBusy(true); setError('');
    try {
      const inspected = await api<Artifact>('/assets/artifacts/inspect', { method: 'POST', body: JSON.stringify({ source_id: source, path: filePath, role }) });
      const existing: unknown = JSON.parse(artifacts);
      if (!Array.isArray(existing)) throw new Error('文件清单必须是数组');
      setArtifacts(pretty([...existing, inspected])); setFilePath('');
    } catch (caught) { setError(caught instanceof Error ? caught.message : '文件校验失败'); }
    finally { setBusy(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const draft: AssetDraft = { asset_id: assetId || prefixes[kind] + '-' + crypto.randomUUID(), kind, name, description,
        tags: tags.split(',').map(x => x.trim()).filter(Boolean), engines: engines.split(',').map(x => x.trim()).filter(Boolean),
        data: JSON.parse(data), references: JSON.parse(references), artifacts: JSON.parse(artifacts), change_note: note };
      const result = await api<{ record: AssetRecord }>('/assets', { method: 'POST', body: JSON.stringify({ draft, expected_version: initial?.version ?? 0 }) });
      window.location.href = assetHref(result.record.asset_id, result.record.version);
    } catch (caught) { setError(caught instanceof Error ? caught.message : '发布失败'); }
    finally { setBusy(false); }
  }

  return <Card><CardHeader><CardTitle>{initial ? '发布新版本 · 保留历史记录' : '登记新资产'}</CardTitle></CardHeader><CardContent>
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <label className="space-y-1 text-sm">类型<NativeSelect aria-label="登记资产类型" disabled={Boolean(initial)} value={kind} onChange={e => setKind(e.target.value as AssetKind)}>{Object.entries(kindLabels).map(([key, label]) => <NativeSelectOption key={key} value={key}>{label}</NativeSelectOption>)}</NativeSelect></label>
        <label className="space-y-1 text-sm">固定编号<Input aria-label="固定编号" value={assetId} disabled={Boolean(initial)} placeholder={prefixes[kind] + '-自动生成或自定义'} onChange={e => setAssetId(e.target.value)} /></label>
        <label className="space-y-1 text-sm">名称<Input aria-label="资产名称" required value={name} onChange={e => setName(e.target.value)} /></label>
      </div>
      <label className="block space-y-1 text-sm">说明<Textarea aria-label="资产说明" value={description} onChange={e => setDescription(e.target.value)} /></label>
      <div className="grid gap-3 md:grid-cols-2"><label className="space-y-1 text-sm">标签（逗号分隔）<Input value={tags} onChange={e => setTags(e.target.value)} /></label><label className="space-y-1 text-sm">适用引擎（逗号分隔）<Input value={engines} placeholder="genesis, isaac_sim, newton" onChange={e => setEngines(e.target.value)} /></label></div>
      <label className="block space-y-1 text-sm">参数与记录内容<Textarea aria-label="参数与记录内容" className="min-h-48 font-mono text-xs" value={data} onChange={e => setData(e.target.value)} /></label>
      <p className="text-xs text-muted-foreground">材料参数请同时保存 value 和 unit；配置关联明确版本，发布后旧验证结果不会自动转移到新版本。</p>
      <label className="block space-y-1 text-sm">关联资产<Textarea aria-label="关联资产" className="font-mono text-xs" value={references} onChange={e => setReferences(e.target.value)} /></label>
      <p className="text-xs text-muted-foreground">格式示例：{'[{"asset_id":"MAT-cloth-light","version":1,"role":"material"}]'}</p>
      <div className="rounded-lg border p-3"><p className="mb-2 text-sm font-medium">关联已有文件</p><div className="grid gap-2 md:grid-cols-4"><Input aria-label="来源编号" value={source} onChange={e => setSource(e.target.value)} /><Input aria-label="来源目录内的文件路径" value={filePath} placeholder="runs/scenes/.../preview.png" onChange={e => setFilePath(e.target.value)} /><Input aria-label="文件用途" value={role} placeholder="preview / model / source" onChange={e => setRole(e.target.value)} /><Button type="button" variant="outline" disabled={busy || !filePath} onClick={() => void addArtifact()}>校验并添加文件</Button></div></div>
      <details><summary className="cursor-pointer text-sm">查看 / 编辑文件清单</summary><Textarea aria-label="文件清单" className="mt-2 min-h-32 font-mono text-xs" value={artifacts} onChange={e => setArtifacts(e.target.value)} /></details>
      <label className="block space-y-1 text-sm">本次变更说明<Input aria-label="变更说明" required value={note} placeholder="记录修改内容及依据" onChange={e => setNote(e.target.value)} /></label>
      {error && <p role="alert" className="break-all text-sm text-destructive">{error}</p>}
      <div className="flex gap-2"><Button disabled={busy} type="submit">{busy ? '正在校验…' : initial ? '发布 v' + (initial.version + 1) : '登记 v1'}</Button><Button type="button" variant="outline" onClick={onCancel}>取消</Button></div>
    </form>
  </CardContent></Card>;
}

export function AssetDetail() {
  const [detail, setDetail] = useState<AssetDetailResponse>();
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    const id = decodeURIComponent(window.location.pathname.split('/').filter(Boolean).at(-1) ?? '');
    const version = new URLSearchParams(window.location.search).get('version');
    const controller = new AbortController();
    void api<AssetDetailResponse>('/assets/' + encodeURIComponent(id) + (version ? '?version=' + encodeURIComponent(version) : ''), { signal: controller.signal }).then(setDetail).catch(caught => {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : '加载失败');
    });
    return () => controller.abort();
  }, []);
  if (error) return <div role="alert" className="space-y-3"><a href="/assets" className="text-primary">返回资产库</a><p className="text-destructive">{error}</p></div>;
  if (!detail) return <p className="text-muted-foreground">正在加载资产版本与证据…</p>;
  const record = detail.record;
  const latest = Math.max(...detail.versions.map(v => v.version));
  const artifactUrl = (index: number) => API_BASE + '/assets/' + encodeURIComponent(record.asset_id) + '/versions/' + record.version + '/artifacts/' + index;
  const previewIndex = record.artifacts.findIndex(a => a.role === 'preview');
  const viewerIndex = record.artifacts.findIndex(a => a.role === 'interactive_preview' || a.role === 'interactive_replay');
  return <div className="space-y-5">
    <a href="/assets" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-primary"><ArrowLeft className="size-4" />资产库</a>
    <div className="flex flex-wrap items-end justify-between gap-3"><div><Badge variant="outline">{kindLabels[record.kind]} · v{record.version}</Badge><h1 className="mt-3 text-2xl font-semibold">{record.name}</h1><p className="mt-2 break-all font-mono text-xs text-muted-foreground">{record.asset_id}</p></div><Button disabled={record.version !== latest} onClick={() => setEditing(!editing)}><GitBranch />发布新版本</Button></div>
    {record.version !== latest && <p className="text-sm text-muted-foreground">正在查看历史版本。<a href={assetHref(record.asset_id)} className="text-primary">前往最新版本发布修改</a></p>}
    {editing && <AssetEditor initial={record} onCancel={() => setEditing(false)} />}
    <div className="flex flex-wrap gap-2"><Badge variant={detail.integrity.status === 'stale' ? 'destructive' : 'outline'}>{detail.integrity.status === 'current' ? '来源文件与引用版本一致' : '证据过期 / 文件缺失'}</Badge>{record.kind === 'validation' && <Badge variant={record.data.outcome === 'failed' ? 'destructive' : 'outline'}>原记录结果：{outcomeLabel(record.data.outcome)}</Badge>}{record.tags.map(tag => <Badge variant="outline" key={tag}>{tag}</Badge>)}</div>
    {detail.integrity.issues.length > 0 && <div role="alert" className="rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{detail.integrity.issues.map(issue => <p className="break-all" key={issue}>{issue}</p>)}<p className="mt-2">原结果保留，但当前文件不能直接沿用该验证结论。</p></div>}
    <p className="text-sm text-muted-foreground">{record.description}</p>
    <div className="grid gap-5 xl:grid-cols-3">
      <div className="space-y-5 xl:col-span-2">
        {viewerIndex >= 0 && detail.integrity.status === 'current' && <Card><CardHeader><CardTitle>{record.kind === 'validation' ? '三维轨迹回放' : record.tags.includes('clothforge') ? '原始几何预览 · 工位外观见实时相机' : '三维衣物预览'}</CardTitle></CardHeader><CardContent><iframe title={record.kind === 'validation' ? '三维轨迹回放' : record.tags.includes('clothforge') ? '原始几何预览 · 工位外观见实时相机' : '三维衣物预览'} className="h-[540px] w-full rounded-lg border bg-slate-950" sandbox="allow-scripts" src={artifactUrl(viewerIndex) + '/viewer'} /></CardContent></Card>}
        {record.kind === 'model' && record.tags.includes('clothforge') && <GarmentAppearancePanel key={record.asset_id + ':' + record.version} record={record} disabled={record.version !== latest || detail.integrity.status !== 'current'} />}
        <ClothRunPanel record={record} integrity={detail.integrity} />
        {viewerIndex < 0 && previewIndex >= 0 && detail.integrity.status === 'current' && <Card><CardContent className="pt-5"><img className="max-h-[440px] w-full rounded-lg object-contain" alt={record.name + ' 模型预览'} src={artifactUrl(previewIndex)} /></CardContent></Card>}
        {record.kind === 'material' && record.data.parameters && typeof record.data.parameters === 'object' ? <Card><CardHeader><CardTitle>材料参数</CardTitle></CardHeader><CardContent><dl className="divide-y">{Object.entries(record.data.parameters as Record<string, { value?: unknown; unit?: string }>).map(([key, param]) => <div className="grid grid-cols-3 gap-3 py-3 text-sm" key={key}><dt className="font-mono text-xs">{key}</dt><dd>{pretty(param && typeof param === 'object' ? param.value : param)}</dd><dd className="text-muted-foreground">{param?.unit ?? ''}</dd></div>)}</dl><p className="mt-3 text-xs text-muted-foreground">{record.data.calibrated === true ? '登记为已标定；具体依据见关联记录。' : '合成预设 / 尚未实物标定'}</p></CardContent></Card> : null}
        <Card><CardHeader><CardTitle>{record.kind === 'validation' ? '指标与判定条件' : '参数与版本内容'}</CardTitle></CardHeader><CardContent><pre className="max-h-[600px] overflow-auto rounded-lg bg-muted/40 p-4 font-mono text-xs leading-6">{pretty(record.data)}</pre></CardContent></Card>
        <Card><CardHeader><CardTitle>来源文件</CardTitle></CardHeader><CardContent className="space-y-3">{record.artifacts.length === 0 && <p className="text-sm text-muted-foreground">该版本没有附属文件。</p>}{record.artifacts.map((artifact, index) => <div key={artifact.source_id + artifact.path + index} className="rounded-lg border p-3"><div className="flex items-center justify-between gap-3"><span className="break-all text-sm">{artifact.path}</span><a className="shrink-0 text-primary" href={artifactUrl(index)} aria-label={'下载 ' + artifact.path}><Download className="size-4" /></a></div><p className="mt-1 text-xs text-muted-foreground">{artifact.source_id} · {artifact.role} · {bytes(artifact.size_bytes ?? 0)}</p><p className="mt-2 break-all font-mono text-[10px] text-muted-foreground">SHA-256 {artifact.sha256}</p></div>)}</CardContent></Card>
      </div>
      <div className="space-y-5">
        <Card><CardHeader><CardTitle>引用版本</CardTitle></CardHeader><CardContent className="space-y-3">{record.references.length === 0 && <p className="text-sm text-muted-foreground">没有依赖资产。</p>}{record.references.map(ref => <a className="block break-all rounded-lg border p-3 text-xs hover:border-primary" key={ref.asset_id + ref.role} href={assetHref(ref.asset_id, ref.version)}><span className="block text-muted-foreground">{ref.role}</span><span className="font-mono text-primary">{ref.asset_id} @v{ref.version}</span></a>)}</CardContent></Card>
        <Card><CardHeader><CardTitle>被哪些记录引用</CardTitle></CardHeader><CardContent className="max-h-96 space-y-3 overflow-auto">{detail.referenced_by.length === 0 && <p className="text-sm text-muted-foreground">此版本暂无关联验证或下游资产。</p>}{detail.referenced_by.map(ref => <a className="block rounded-lg border p-3 text-sm hover:border-primary" key={ref.asset_id + ref.version} href={assetHref(ref.asset_id, ref.version)}>{ref.name}<span className="mt-1 block text-xs text-muted-foreground">v{ref.version} · {kindLabels[ref.kind]}{ref.outcome ? ' · ' + outcomeLabel(ref.outcome) : ''}</span></a>)}</CardContent></Card>
        <Card><CardHeader><CardTitle>版本历史</CardTitle></CardHeader><CardContent className="space-y-3">{[...detail.versions].reverse().map(v => <a key={v.version} className="block rounded-lg border p-3 hover:border-primary" href={assetHref(record.asset_id, v.version)}><strong className="text-sm">v{v.version}</strong><p className="mt-1 text-xs text-muted-foreground">{v.change_note}</p><p className="mt-1 font-mono text-[10px] text-muted-foreground">{v.created_at}</p></a>)}</CardContent></Card>
      </div>
    </div>
  </div>;
}
