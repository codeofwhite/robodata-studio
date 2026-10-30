'use client';
import { useEffect, useState } from 'react';
import { api, API_BASE } from '@/lib/api';
import type { Appearance, PbrMaterial } from '@/lib/pbr-material-types';
import { pbrDefaults } from '@/lib/pbr-material-types';
import { PbrMaterialPreview } from './pbr-material-preview';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { NativeSelect, NativeSelectOption } from './ui/native-select';

export function PbrMaterialLibrary() {
  const [items, setItems] = useState<PbrMaterial[]>([]);
  const [selected, setSelected] = useState('');
  const [category, setCategory] = useState<'fabric' | 'tabletop' | 'background'>('fabric');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [value, setValue] = useState<Appearance>({ texture: 'none', color: '#ffffff', roughness: .9, ...pbrDefaults });
  const item = items.find(entry => entry.asset_id === selected);
  async function refresh() {
    const result = await api<{ items: PbrMaterial[] }>('/pbr-materials'); setItems(result.items);
    setSelected(current => current || result.items[0]?.asset_id || '');
  }
  useEffect(() => { void refresh().catch(e => setError(String(e))); }, []);
  useEffect(() => { const requested = new URLSearchParams(window.location.search).get('category'); if (requested === 'tabletop' || requested === 'background') setCategory(requested); }, []);
  useEffect(() => { setSelected(current => items.some(item => item.asset_id === current && (item.data.category ?? 'fabric') === category) ? current : items.find(item => (item.data.category ?? 'fabric') === category)?.asset_id ?? ''); }, [items, category]);
  async function upload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; setBusy(true); setError('');
    try {
      const response = await fetch(API_BASE + '/pbr-materials', { method: 'POST', body: new FormData(form) });
      const result = await response.json() as { asset_id: string; detail?: unknown }; if (!response.ok) throw new Error(JSON.stringify(result.detail));
      await refresh(); setSelected(result.asset_id); form.reset();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  return <div className="space-y-5">
    <div><h2 className="text-xl font-semibold">PBR 材质库</h2><p className="text-sm text-muted-foreground">衣物、桌面和背景共用本地素材库。选择材质后，可在下方检查表面细节。</p></div>
    <label>材质分类<NativeSelect aria-label="材质分类" value={category} onChange={e => setCategory(e.target.value as typeof category)}><NativeSelectOption value="fabric">织物</NativeSelectOption><NativeSelectOption value="tabletop">桌面</NativeSelectOption><NativeSelectOption value="background">背景墙</NativeSelectOption></NativeSelect></label>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    <div className="grid gap-5 lg:grid-cols-2"><div className="grid grid-cols-2 gap-3">
      {items.filter(entry => (entry.data.category ?? 'fabric') === category).map(entry => <button key={entry.asset_id} onClick={() => setSelected(entry.asset_id)} className={'rounded border p-3 text-left ' + (selected === entry.asset_id ? 'border-primary' : '')}>
        <img crossOrigin="anonymous" src={API_BASE + entry.maps.base_color.url} alt={entry.name} className="mb-2 h-28 w-full rounded object-cover" />
        <span>{entry.name}</span><p className="text-xs text-muted-foreground">v{entry.version} · {entry.data.license}</p>
      </button>)}
      {!items.length && <p>暂无材质，可从下方导入。</p>}
    </div><div className="space-y-3">{item && <><PbrMaterialPreview material={item} appearance={value} surface={category !== 'fabric'} /><PbrTuning value={value} onChange={setValue} surface={category !== 'fabric'} /><p className="text-sm">{item.name} · {item.data.dimensions_px.join('×')} · {item.data.license}</p>{/^https?:\/\//.test(item.data.origin) && <a className="text-primary" href={item.data.origin} target="_blank" rel="noreferrer">素材来源</a>}<a className="ml-3 text-primary" href="/generation#cloth-generation">用于衣物批量生成</a></>}</div></div>
    <form onSubmit={event => void upload(event)} className="space-y-3 rounded border p-4"><h3 className="font-semibold">本地导入</h3><fieldset disabled={busy} className="grid gap-3 sm:grid-cols-2">
      <input type="hidden" name="category" value={category} />
      <label>名称<Input name="name" required maxLength={200} /></label><label>来源<Input name="origin" placeholder="素材页面 URL 或本地来源说明" /></label>
      <label>许可<Input name="license_name" placeholder="例如 CC0-1.0；填写原始许可" /></label>
      {(['base_color', 'normal', 'roughness'] as const).map(role => <label key={role}>{role === 'normal' ? 'Normal（OpenGL）' : role === 'base_color' ? 'BaseColor' : 'Roughness'}<Input type="file" name={role} accept="image/png" required /></label>)}
    </fieldset><p className="text-xs text-muted-foreground">三张贴图使用相同分辨率的 PNG；导入不会修改衣物物理材料。</p><Button disabled={busy} type="submit">{busy ? '导入中…' : '导入材质'}</Button></form>
  </div>;
}

export function PbrTuning({ value, onChange, surface = false }: { value: Appearance; onChange: (next: Appearance) => void; surface?: boolean }) {
  return <div className="grid gap-3 sm:grid-cols-2">
    <label>颜色模式<NativeSelect value={value.color_mode ?? 'original'} onChange={e => onChange({ ...value, color_mode: e.target.value as 'original' | 'tint' })}><NativeSelectOption value="original">保留贴图原色</NativeSelectOption><NativeSelectOption value="tint">染色</NativeSelectOption></NativeSelect></label>
    {value.color_mode === 'tint' && <label>染色颜色<Input type="color" value={value.color} onChange={e => onChange({ ...value, color: e.target.value })} /></label>}
    {([['roughness_multiplier', '粗糙度倍率', 0, 2], ['normal_strength', '法线强度', 0, 2], ['uv_scale', surface ? '每米纹理重复次数' : '纹理重复次数', .1, 50]] as const).map(([key, label, min, max]) => <label key={key}>{label}<Input type="number" min={min} max={max} step={.1} value={value[key] ?? 1} onChange={e => onChange({ ...value, [key]: Number(e.target.value) })} /></label>)}
  </div>;
}
