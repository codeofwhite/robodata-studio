'use client';
import type { Appearance, EnvironmentAppearance, PbrMaterial } from '@/lib/pbr-material-types';
import { pbrDefaults } from '@/lib/pbr-material-types';
import { NativeSelect, NativeSelectOption } from './ui/native-select';
import { Input } from './ui/input';
import { PbrTuning } from './pbr-material-library';
import { PbrMaterialPreview } from './pbr-material-preview';

export function SurfaceAppearanceControls({ value, materials, onChange, disabled }: {
  value: EnvironmentAppearance; materials: PbrMaterial[];
  onChange: (value: EnvironmentAppearance) => void; disabled?: boolean;
}) {
  const defaults: Appearance = { texture: 'none', color: '#ffffff', roughness: .8, ...pbrDefaults };
  return <fieldset disabled={disabled} className="space-y-4 disabled:opacity-60">
    {(['tabletop', 'background'] as const).map(target => {
      const appearance = value[target];
      const material = materials.find(m => m.asset_id === appearance?.material_id && m.version === appearance?.material_version);
      const change = (next: Appearance | null) => onChange({ ...value, [target]: next });
      return <div key={target} className="space-y-3 rounded border p-3" data-surface-target={target}>
        <label>{target === 'tabletop' ? '桌面材质' : '背景墙材质'}<NativeSelect aria-label={target === 'tabletop' ? '桌面材质' : '背景墙材质'} value={appearance?.material_id ?? (appearance ? 'solid' : 'original')} onChange={e => {
          if (e.target.value === 'original') return change(null);
          const picked = materials.find(m => m.asset_id === e.target.value);
          change({ ...defaults, ...appearance, texture: 'none', material_id: picked?.asset_id ?? null,
                   material_version: picked?.version ?? null, color_mode: 'original' });
        }}><NativeSelectOption value="original">保持场景原材质</NativeSelectOption><NativeSelectOption value="solid">纯色</NativeSelectOption>
          {materials.filter(m => m.data.category === target || m.asset_id === appearance?.material_id).map(m => <NativeSelectOption key={m.asset_id} value={m.asset_id}>{m.name} · v{m.version}</NativeSelectOption>)}
        </NativeSelect></label>
        {appearance && (material ? <><PbrTuning value={appearance} onChange={change} surface /><PbrMaterialPreview material={material} appearance={appearance} surface /></> : <div className="grid gap-3 sm:grid-cols-2">
          <label>基础颜色<Input aria-label={target + '颜色'} type="color" value={appearance.color} onChange={e => change({ ...appearance, color: e.target.value })} /></label>
          <label>粗糙度<Input type="number" min={0} max={1} step={.05} value={appearance.roughness} onChange={e => change({ ...appearance, roughness: Number(e.target.value) })} /></label>
        </div>)}
      </div>;
    })}
    <p className="text-xs text-muted-foreground">启动时应用；纹理按每米重复次数铺设。桌面和背景外观独立配置。</p>
  </fieldset>;
}
