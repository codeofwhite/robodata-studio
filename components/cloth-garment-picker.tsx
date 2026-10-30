'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { assetHref, type AssetRecord } from '@/lib/asset-types';
import { pbrDefaults, type Appearance, type PbrMaterial } from '@/lib/pbr-material-types';
import { AppearanceControls, type AppearanceOptions } from './garment-appearance-panel';
import { ClothGarmentPreview, type GarmentMesh } from './cloth-garment-preview';
import { Button } from './ui/button';

export function previewAppearance(record: AssetRecord, material?: PbrMaterial): Appearance {
  const saved = record.data.appearance as Appearance | undefined;
  return saved ?? { texture: 'none', color: '#ffffff', roughness: .9, ...pbrDefaults,
    material_id: material?.asset_id ?? null, material_version: material?.version ?? null };
}

type StyleOptions = { styles: { id: string; name: string; defaults: Record<string,number|string> }[]; fields: Record<string,{label:string;min:number;max:number;step:number}> };
type StylePreview = { preview_id:string; style_id:string; parameters:Record<string,number>; mesh:GarmentMesh };

export function ClothGarmentPicker({ variants, materials, selected, onSelectionChange }: {
  variants: AssetRecord[]; materials: PbrMaterial[]; selected: string[]; onSelectionChange: (ids: string[]) => void;
}) {
  const [record, setRecord] = useState(variants[0]);
  const [value, setValue] = useState<Appearance>(() => previewAppearance(variants[0], materials[0]));
  const [options, setOptions] = useState<AppearanceOptions>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [styleOptions, setStyleOptions] = useState<StyleOptions>();
  const [styleId, setStyleId] = useState('');
  const [styleParameters, setStyleParameters] = useState<Record<string,number>>({});
  const [generated, setGenerated] = useState<StylePreview>();
  const [generating, setGenerating] = useState(false);
  const stylePrefix = record.data.supports_style_editing===false?null:record.data.category==='trousers'?'trouser':record.data.category==='tshirt'?'tshirt':record.data.category==='skirt'?'skirt':null;
  const styleLabel = record.data.category==='trousers'?'长裤款式':record.data.category==='skirt'?'半身裙款式':'短袖领型';
  const material = materials.find(m => m.asset_id === value.material_id && m.version === value.material_version);
  const sizes = [...variants].sort((a,b) => Number((a.data.parameters as Record<string, number>).length_m) - Number((b.data.parameters as Record<string, number>).length_m));
  const dimensions = generated?.parameters ?? record.data.parameters as Record<string, number>;
  useEffect(() => {
    setStyleOptions(undefined); setStyleId(''); setStyleParameters({});
    if (!stylePrefix) return;
    const controller = new AbortController();
    void api<StyleOptions>(`/assets/${stylePrefix}-styles/options`, {signal:controller.signal}).then(setStyleOptions).catch(e => {if(!controller.signal.aborted)setError(String(e));});
    return () => controller.abort();
  }, [stylePrefix]);
  useEffect(() => {
    if (!styleId) { setGenerated(undefined); setGenerating(false); return; }
    const controller = new AbortController(); setGenerating(true); setGenerated(undefined); setError('');
    const timer = setTimeout(() => {
      void api<StylePreview>(`/assets/${stylePrefix}-styles/previews`, {method:'POST',signal:controller.signal,body:JSON.stringify({asset_id:record.asset_id,version:record.version,style_id:styleId,parameters:styleParameters})})
        .then(result => {if(!controller.signal.aborted)setGenerated(result);})
        .catch(e => {if(!controller.signal.aborted)setError(String(e));})
        .finally(() => {if(!controller.signal.aborted)setGenerating(false);});
    }, 600);
    return () => {clearTimeout(timer);controller.abort();};
  }, [record.asset_id, record.version, styleId, styleParameters, stylePrefix]);
  useEffect(() => {
    const controller = new AbortController(); setOptions(undefined); setError('');
    void api<AppearanceOptions>(`/assets/${encodeURIComponent(record.asset_id)}/appearance-options?version=${record.version}`, { signal: controller.signal })
      .then(next => { if (!controller.signal.aborted) setOptions({ ...next, materials }); })
      .catch(e => { if (!controller.signal.aborted) setError(String(e)); });
    return () => controller.abort();
  }, [record.asset_id, record.version, materials]);
  async function saveAndOpen() {
    if (!options || generating || (styleId && !generated)) return;
    setBusy(true); setError('');
    const { asset_id, kind, name, description, tags, engines, data, references, artifacts } = record;
    const texture = options.textures.find(t => t.id === value.texture);
    try {
      const result = generated ? await api<{record:AssetRecord}>(`/assets/${stylePrefix}-styles/previews/${generated.preview_id}/save`, {method:'POST',body:JSON.stringify(value)}) : await api<{ record: AssetRecord }>('/assets', { method: 'POST', body: JSON.stringify({ expected_version: record.version,
        draft: { asset_id, kind, name, description, tags, engines, references,
          data: { ...data, appearance: { ...value, texture_sha256: texture?.artifact?.sha256 ?? null } },
          artifacts: [...artifacts.filter(a => a.role !== 'visual_texture'), ...(texture?.artifact ? [texture.artifact] : [])],
          change_note: '衣物库实时预览：保存选定尺寸变体的材质外观',
        } }) });
      window.location.href = `/sessions/new?engine=isaac_sim&scene=bimanual_tabletop_v17_clothforge&garment=${encodeURIComponent(result.record.asset_id)}&version=${result.record.version}`;
    } catch (e) { setError(String(e)); setBusy(false); }
  }
  return <div className="mt-3 space-y-3" data-garment-picker={record.asset_id}>
    <label className="block text-xs">{record.data.category==='trousers'?'基础长裤尺寸':record.data.category==='skirt'?'基础半身裙尺寸':'衣长／尺寸变体'}<select aria-label="衣长尺寸" className="mt-1 w-full rounded border bg-background p-2" disabled={busy} value={record.asset_id} onChange={e => {const next=variants.find(v => v.asset_id===e.target.value)!;setRecord(next);if(styleId){const p=next.data.parameters as Record<string,number>;setStyleParameters(current=>({...current,...Object.fromEntries(Object.keys(styleOptions?.fields??{}).filter(k=>typeof p[k]==='number').map(k=>[k,p[k]]))}));}}}>{sizes.map(v => {
      const p = v.data.parameters as Record<string, number>;
      return <option key={v.asset_id} value={v.asset_id}>{v.name} · {v.data.parameter_semantics==='draped_axis_aligned_extents'?'高':'长'} {(p.length_m * 100).toFixed(1)} / {p.waist_width_m ? '腰宽' : '宽'} {((p.width_m ?? p.waist_width_m) * 100).toFixed(1)} cm</option>;
    })}</select></label>
    <p className="text-xs text-muted-foreground">{record.data.parameter_semantics==='draped_axis_aligned_extents'?'外形高':'长'} {(dimensions.length_m * 100).toFixed(1)} · {dimensions.waist_width_m ? '腰宽' : '宽'} {((dimensions.width_m ?? dimensions.waist_width_m) * 100).toFixed(1)} cm{record.data.category==='skirt' && typeof dimensions.hem_width_m==='number' ? ` · 裙摆宽 ${(dimensions.hem_width_m*100).toFixed(1)} cm` : ''}{dimensions.sleeve_m ? ` · 袖长参数 ${(dimensions.sleeve_m * 100).toFixed(1)} cm` : ''}</p>
    {styleOptions && <div className="space-y-2 rounded border p-2">
      <label className="block text-xs">{styleLabel}<select aria-label={styleLabel} className="ml-2 rounded border bg-background p-1" disabled={busy} value={styleId} onChange={e=>{const id=e.target.value;setStyleId(id);const p=record.data.parameters as Record<string,number>;setStyleParameters({...Object.fromEntries(Object.entries(styleOptions.fields).map(([k,f])=>[k,p[k]??f.min])),...Object.fromEntries(Object.entries(styleOptions.styles.find(s=>s.id===id)?.defaults??{}).flatMap(([k,v])=>typeof v==='number'?[[k,v] as const]:[]))});}}><option value="">使用所选衣物</option>{styleOptions.styles.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
      {styleId && Object.entries(styleOptions.fields).map(([key,field])=><label className="block text-xs" key={key}>{field.label} · {((styleParameters[key]??0)*100).toFixed(0)} cm<input aria-label={field.label} className="mt-1 w-full" type="range" min={field.min} max={field.max} step={field.step} disabled={busy} value={styleParameters[key]??field.min} onChange={e=>setStyleParameters(current=>({...current,[key]:Number(e.target.value)}))}/></label>)}
      {styleId && <p role="status" className="text-xs text-muted-foreground">{generating?'正在生成真实网格…':generated?'网格已更新；保存后可进入工位':'调整参数后生成预览'}</p>}
    </div>}
    <ClothGarmentPreview record={generated ? {...record,asset_id:'preview-'+generated.preview_id} : record} previewMesh={generated?.mesh} appearance={value} material={material} />
    {options && <AppearanceControls value={value} options={options} onChange={setValue} disabled={busy} showPreview={false} />}
    <div className="flex flex-wrap items-center gap-3 text-xs">
      <Button size="sm" disabled={busy || !options || generating || !!styleId && !generated} onClick={() => void saveAndOpen()}>{busy ? '保存中…' : '保存外观并进入工位'}</Button>
      <a className="text-primary" href={assetHref(record.asset_id, record.version)}>物理调参／详情</a>
      <label className="flex items-center gap-2"><input type="checkbox" disabled={!!styleId} checked={selected.includes(record.asset_id)} onChange={e => onSelectionChange(e.target.checked ? [...selected, record.asset_id] : selected.filter(id => id !== record.asset_id))} />加入批量</label>
    </div>
    <p className="text-xs text-muted-foreground">{record.data.supports_style_editing===false?'衣物由源版片重建；保存外观后可进入工位。':'款式调整会重新生成真实网格；保存后，几何和外观一起用于工位。'}</p>
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </div>;
}
