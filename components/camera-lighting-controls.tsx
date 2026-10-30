'use client';
import { Input } from './ui/input';
import { NativeSelect, NativeSelectOption } from './ui/native-select';
import { originalCameraLighting, type CameraLightingRequest, type CameraLightingValues } from '@/lib/camera-lighting-types';
const fields: [keyof CameraLightingValues, string, number, number, number][] = [
  ['fov_offset_deg', '垂直 FOV 增量（度）', -15, 15, .5],
  ['camera_x_m', '相机 X 平移（米）', -.3, .3, .01], ['camera_y_m', '相机 Y 平移（米）', -.3, .3, .01], ['camera_z_m', '相机 Z 平移（米）', -.3, .3, .01],
  ['camera_rx_deg', '相机绕世界 X 旋转（度）', -20, 20, .5], ['camera_ry_deg', '相机绕世界 Y 旋转（度）', -20, 20, .5], ['camera_rz_deg', '相机绕世界 Z 旋转（度）', -20, 20, .5],
  ['exposure_ev', '曝光补偿（EV）', -3, 3, .1], ['white_balance_k', '白平衡（K，留空保持原值）', 2000, 10000, 100],
  ['light_intensity_multiplier', '灯光强度倍率', .2, 3, .1], ['light_temperature_k', '灯光色温（K，留空保持原值）', 2000, 10000, 100],
];
export function CameraLightingControls({ value, onChange, disabled }: { value: CameraLightingRequest; onChange: (value: CameraLightingRequest) => void; disabled?: boolean }) {
  const values = { ...originalCameraLighting.values, ...value.values };
  return <fieldset disabled={disabled} className="space-y-4 rounded border p-3" data-camera-lighting>
    <h3 className="font-semibold">Camera & Lighting · 相机与光照</h3>
    <div className="grid gap-3 sm:grid-cols-2"><label>配置方式<NativeSelect aria-label="相机光照配置方式" value={value.mode} onChange={e => onChange({ ...value, mode: e.target.value as 'fixed' | 'uniform', ranges: e.target.value === 'fixed' ? {} : value.ranges })}><NativeSelectOption value="fixed">固定配置</NativeSelectOption><NativeSelectOption value="uniform">均匀采样</NativeSelectOption></NativeSelect></label><label>Seed<Input aria-label="相机光照 Seed" type="number" min={0} max={2147483647} step={1} value={value.seed} onChange={e => onChange({ ...value, seed: Number(e.target.value) })} /></label></div>
    <div className="grid gap-3 sm:grid-cols-2">{fields.map(([key, label, min, max, step]) => <div key={key} className="space-y-2"><label>{label}<Input aria-label={key} type="number" min={min} max={max} step={step} value={values[key] ?? ''} onChange={e => onChange({ ...value, values: { ...values, [key]: e.target.value === '' && key.endsWith('_k') ? null : Number(e.target.value) } })} /></label>
      {value.mode === 'uniform' && <><label className="flex items-center gap-2 text-xs"><input type="checkbox" aria-label={key + '采样'} checked={Boolean(value.ranges[key])} onChange={e => { const ranges = { ...value.ranges }; if (e.target.checked) ranges[key] = [values[key] ?? min, values[key] ?? min]; else delete ranges[key]; onChange({ ...value, ranges }); }} />均匀采样此参数</label>{value.ranges[key] && <div className="flex gap-2">{([0, 1] as const).map(i => <Input key={i} aria-label={key + (i === 0 ? '下限' : '上限')} type="number" min={min} max={max} step={step} value={value.ranges[key]![i]} onChange={e => { const range: [number, number] = [...value.ranges[key]!]; range[i] = Number(e.target.value); onChange({ ...value, ranges: { ...value.ranges, [key]: range } }); }} />)}</div>}</>}
    </div>)}</div>
    <p className="text-xs text-muted-foreground">启动时应用；每组相机共用这些增量，旋转顺序 X→Y→Z，绕各自相机中心。批量计划预览时固定采样结果。参数为仿真设置，D435i 真实内参与光度标定仍待完成。</p>
  </fieldset>;
}
