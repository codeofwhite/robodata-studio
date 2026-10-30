'use client';

import { useEffect, useState } from 'react';
import { api, API_BASE } from '@/lib/api';
import type { Artifact, AssetRecord } from '@/lib/asset-types';
import { assetHref } from '@/lib/asset-types';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';

import { PbrMaterialPreview } from './pbr-material-preview';
import { PbrTuning } from './pbr-material-library';
import type { Appearance, PbrMaterial } from '@/lib/pbr-material-types';
export type { Appearance } from '@/lib/pbr-material-types';
export type AppearanceOptions = { appearance: Appearance; materials?: PbrMaterial[]; textures: { id: string; label: string; artifact: Artifact | null; thumbnail_url: string | null }[] };

export function AppearanceControls({ value, options, onChange, disabled, showPreview = true }: {
  value: Appearance; options: AppearanceOptions; onChange: (next: Appearance) => void; disabled?: boolean; showPreview?: boolean;
}) {
  const material = options.materials?.find(item => item.asset_id === value.material_id && item.version === value.material_version);
  const texture = options.textures.find(item => item.id === value.texture);
  return <fieldset disabled={disabled} className="space-y-3 disabled:opacity-60">
    <label className="text-sm">PBR 材质<NativeSelect value={value.material_id ?? ''} onChange={e => { const entry = options.materials?.find(item => item.asset_id === e.target.value); onChange({ ...value, material_id: entry?.asset_id ?? null, material_version: entry?.version ?? null, texture: entry ? 'none' : value.texture, color_mode: 'original' }); }}><NativeSelectOption value="">旧贴图／纯色</NativeSelectOption>{options.materials?.map(item => <NativeSelectOption key={item.asset_id} value={item.asset_id}>{item.name} · v{item.version}</NativeSelectOption>)}</NativeSelect></label>
    {material ? <><PbrTuning value={value} onChange={onChange} />{showPreview && <PbrMaterialPreview material={material} appearance={value} />}</> : <div className="grid gap-3 sm:grid-cols-3">
      <label className="space-y-1 text-sm">已有贴图<NativeSelect aria-label="衣物贴图" className="w-full" value={value.texture} onChange={e => onChange({ ...value, texture: e.target.value })}>{options.textures.map(item => <NativeSelectOption key={item.id} value={item.id}>{item.label}</NativeSelectOption>)}</NativeSelect></label>
      <label className="space-y-1 text-sm">基础颜色<Input aria-label="衣物基础颜色" type="color" value={value.color} onChange={e => onChange({ ...value, color: e.target.value })} /></label>
      <label className="space-y-1 text-sm">粗糙度<Input aria-label="衣物外观粗糙度" type="number" min={0} max={1} step={0.05} value={value.roughness} onChange={e => onChange({ ...value, roughness: Number(e.target.value) })} /></label>
    </div>}
    {showPreview && !material && <div className="flex items-center gap-3 rounded-lg border p-3">
      {texture?.thumbnail_url ? <img className="size-20 rounded object-cover" src={API_BASE + texture.thumbnail_url} alt={texture.label + '贴图样本'} /> : <span className="size-20 rounded border" style={{ backgroundColor: value.color }} />}
      <p className="text-xs text-muted-foreground">贴图样本 · 基础颜色会与贴图相乘。完整效果在工位相机中预览，录制使用同一材质。参数在启动时生效。</p>
    </div>}
  </fieldset>;
}

export function GarmentAppearancePanel({ record, disabled }: { record: AssetRecord; disabled?: boolean }) {
  const [options, setOptions] = useState<AppearanceOptions>();
  const [value, setValue] = useState<Appearance>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void api<AppearanceOptions>(`/assets/${encodeURIComponent(record.asset_id)}/appearance-options?version=${record.version}`, { signal: controller.signal })
      .then(next => { setOptions(next); setValue(next.appearance); })
      .catch(e => { if (!controller.signal.aborted) setError(String(e)); });
    return () => controller.abort();
  }, [record.asset_id, record.version]);
  async function save() {
    if (!value || !options) return;
    setBusy(true); setError('');
    try {
      const material = options.materials?.find(item => item.asset_id === value.material_id && item.version === value.material_version);
  const texture = options.textures.find(item => item.id === value.texture);
      const { asset_id, kind, name, description, tags, engines, data, references, artifacts } = record;
      const result = await api<{ record: AssetRecord }>('/assets', { method: 'POST', body: JSON.stringify({
        expected_version: record.version,
        draft: { asset_id, kind, name, description, tags, engines, references,
          data: { ...data, appearance: { ...value, texture_sha256: texture?.artifact?.sha256 ?? null } },
          artifacts: [...artifacts.filter(item => item.role !== 'visual_texture'), ...(texture?.artifact ? [texture.artifact] : [])],
          change_note: '更新衣物外观：贴图、基础颜色与粗糙度',
        },
      }) });
      window.location.href = assetHref(result.record.asset_id, result.record.version);
    } catch (e) { setError(String(e)); setBusy(false); }
  }
  return <Card><CardHeader><CardTitle>衣物工位外观</CardTitle></CardHeader><CardContent className="space-y-4">
    {options && value ? <AppearanceControls value={value} options={options} onChange={setValue} disabled={disabled || busy} /> : !error && <p className="text-sm text-muted-foreground">正在加载外观…</p>}
    <p className="text-xs text-muted-foreground">保存为衣物新版本后，进入工位预览。外观配置保留原有物理材料参数。</p>
    <div className="flex flex-wrap gap-3"><Button disabled={disabled || busy || !value} onClick={() => void save()}>{busy ? '保存中…' : '保存外观为新版本'}</Button><a className="inline-flex items-center text-sm text-primary" href={`/sessions/new?engine=isaac_sim&scene=bimanual_tabletop_v17_clothforge&garment=${encodeURIComponent(record.asset_id)}&version=${record.version}`}>用此版本进入工位预览</a></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </CardContent></Card>;
}
