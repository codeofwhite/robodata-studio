export type Appearance = {
  texture: string; color: string; roughness: number; texture_sha256?: string | null;
  material_id?: string | null; material_version?: number | null; color_mode?: 'original' | 'tint';
  roughness_multiplier?: number; normal_strength?: number; uv_scale?: number;
};
export type PbrMaterial = {
  asset_id: string; version: number; name: string;
  data: { license: string; origin: string; dimensions_px: number[]; category?: 'fabric' | 'tabletop' | 'background' };
  maps: Record<'base_color' | 'normal' | 'roughness', { url: string; artifact: { sha256: string } }>;
};
export type EnvironmentAppearance = { tabletop: Appearance | null; background: Appearance | null };
export type AppearanceVariant = Appearance & { environment?: EnvironmentAppearance };
export const originalEnvironment: EnvironmentAppearance = { tabletop: null, background: null };
export const pbrDefaults = { color_mode: 'original' as const, roughness_multiplier: 1, normal_strength: 1, uv_scale: 1 };
export function appearanceParams(value: Appearance) {
  return { visual_texture: value.texture, visual_color: value.color, visual_roughness: value.roughness,
    visual_material_id: value.material_id ?? null, visual_material_version: value.material_version ?? null,
    visual_color_mode: value.color_mode ?? 'original', visual_roughness_multiplier: value.roughness_multiplier ?? 1,
    visual_normal_strength: value.normal_strength ?? 1, visual_uv_scale: value.uv_scale ?? 1 };
}
