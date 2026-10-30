export type AssetKind = 'scene' | 'material' | 'model' | 'config' | 'validation';
export const kindLabels: Record<AssetKind, string> = { scene: '场景', material: '材料', model: '模型', config: '配置', validation: '验证记录' };
export const prefixes: Record<AssetKind, string> = { scene: 'SCN', material: 'MAT', model: 'MDL', config: 'CFG', validation: 'VAL' };
export type AssetRef = { asset_id: string; version: number; role: string };
export type Artifact = { source_id: string; path: string; role: string; sha256: string | null; size_bytes: number | null };
export type AssetDraft = { asset_id: string; kind: AssetKind; name: string; description: string; tags: string[]; engines: string[]; data: Record<string, unknown>; references: AssetRef[]; artifacts: Artifact[]; change_note: string };
export type AssetRecord = AssetDraft & { version: number; created_at: string; content_sha256: string };
export type Integrity = { status: 'current' | 'stale'; issues: string[] };
export type AssetList = { items: (AssetRecord & { integrity: Integrity })[]; counts: Record<AssetKind, number>; total: number; offset: number; limit: number; revision_count: number };
export type AssetDetailResponse = { record: AssetRecord; integrity: Integrity; versions: { version: number; created_at: string; change_note: string; content_sha256: string }[]; referenced_by: { asset_id: string; version: number; kind: AssetKind; name: string; outcome?: string }[] };
export function assetHref(id: string, version?: number) { return '/assets/' + encodeURIComponent(id) + (version ? '?version=' + version : ''); }
export function outcomeLabel(value: unknown) { return value === 'passed' ? '通过' : value === 'failed' ? '失败' : value === 'unavailable' ? '未判定' : '—'; }

export type ValidationStatus = 'both_passed' | 'genesis_only' | 'isaac_only' | 'newton_only' | 'physics_passed' | 'needs_repair' | 'unverified' | 'stale' | 'mixed';
export type FailureCount = { gate: string; count: number };
export type ValidationTrial = { asset_id: string; version: number; engine_id: string; outcome: string; evaluator_version: string; scope: string; source_trial: string; failed_gates: string[]; integrity: Integrity; video: { url: string; path: string } | null; replay: { url: string; path: string } | null; scenario?: string };
export type EngineValidation = { passed: number; total: number; status: string; protocols: { evaluator_version: string; scope: string; scenario: string; passed: number; total: number; status: string }[]; failures: FailureCount[]; representative: ValidationTrial | null };
export type ValidationRow = { asset_id: string; version: number; name: string; tags: string[]; status: ValidationStatus; integrity: Integrity; engines: Record<string, EngineValidation>; failures: (FailureCount & { engine_id: string })[]; trials: ValidationTrial[]; historical_count: number };
export type ValidationOverviewResponse = { items: ValidationRow[]; summary: { configs: number; ready: number; physics_checked: number; interactive_replays: number; needs_repair: number; unverified: number; stale: number; mixed: number; validations: number; current_version_trials: number; unlinked_validations: number; videos: number; configs_with_video: number }; minimum_repeats: number };

export type ClothRun = { run_id: string; status: 'queued' | 'running' | 'completed' | 'failed'; engine_id: 'genesis' | 'newton_vbd'; progress: number; config_asset_id: string; config_version: number; created_at: string; started_at: string | null; finished_at: string | null; validation_asset_id: string | null; validation_version: number | null; outcome: 'passed' | 'failed' | 'unavailable' | null; error: string | null; log_tail: string };

export type ClothField = { label: string; unit?: string; min?: number; max?: number; step?: number; choices?: number[] };
export type ClothOptions = { model_asset_id: string; model_version: number; garment_id: string; category: string; presets: { id: string; name: string; parameters: Record<string, number | string> }[]; default_material: string; default_scenario: string; initial_material: Record<string, number | string> | null; initial_solver: Record<string, number>; recommended_solvers: Record<string, Record<string, Record<string, number>>>; material_fields: Record<string, ClothField>; solver_fields: Record<string, ClothField>; scenarios: { id: string; label: string }[]; duration_s: number; gpu: number };
