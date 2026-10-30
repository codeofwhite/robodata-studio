export type CameraLightingValues = {
  fov_offset_deg: number; camera_x_m: number; camera_y_m: number; camera_z_m: number;
  camera_rx_deg: number; camera_ry_deg: number; camera_rz_deg: number; exposure_ev: number;
  white_balance_k: number | null; light_intensity_multiplier: number; light_temperature_k: number | null;
};
export type CameraLightingRequest = { mode: 'fixed' | 'uniform'; seed: number; values: CameraLightingValues; ranges: Partial<Record<keyof CameraLightingValues, [number, number]>> };
export type CameraLightingResolved = { request: CameraLightingRequest; sample_seed: number; values: CameraLightingValues };
export const originalCameraLighting: CameraLightingRequest = { mode: 'fixed', seed: 0, ranges: {}, values: {
  fov_offset_deg: 0, camera_x_m: 0, camera_y_m: 0, camera_z_m: 0,
  camera_rx_deg: 0, camera_ry_deg: 0, camera_rz_deg: 0, exposure_ev: 0,
  white_balance_k: null, light_intensity_multiplier: 1, light_temperature_k: null,
} };
export function cameraLightingSummary(value?: CameraLightingResolved) {
  if (!value) return '原相机与光照';
  const v = value.values;
  return `FOV ${v.fov_offset_deg.toFixed(2)}° · EV ${v.exposure_ev.toFixed(2)} · 灯光 ×${v.light_intensity_multiplier.toFixed(2)} · WB ${v.white_balance_k?.toFixed(0) ?? '原值'} K · Seed ${value.request.seed}`;
}
