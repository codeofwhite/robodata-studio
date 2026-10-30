'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Box, Database, FileArchive, RefreshCw, ShieldCheck } from 'lucide-react';

import { AppShell } from '@/components/app-shell';
import { useStudioCapabilities } from '@/hooks/use-studio-capabilities';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api } from '@/lib/api';
import { engineLabel } from '@/lib/engines';
import type { ConsumerSmoke, Dataset, Episode, ExportEpisodeRef, ExportJob, ExportPreflight } from '@/lib/types';

type ExportFormat = 'lerobot' | 'openpi_lerobot_v21' | 'rlds' | 'robomimic';
type TrainingProfile = 'physical_joint8' | 'openpi_franka_joint8' | 'fastwam_franka_joint8';
type EngineFilter = 'all' | 'genesis' | 'isaac_sim' | 'roboverse';

const formats = [
  { id: 'lerobot', title: 'LeRobot v3', note: '当前 LeRobot 与 FastWAM consumer', icon: Box },
  { id: 'openpi_lerobot_v21', title: 'OpenPI LeRobot v2.1', note: 'OpenPI vendored loader 的原生兼容格式', icon: Box },
  { id: 'rlds', title: 'RLDS', note: 'TensorFlow Datasets episode/step 结构', icon: Database },
  { id: 'robomimic', title: 'Robomimic HDF5', note: 'HDF5 demos、mask 与相机观测', icon: FileArchive },
] as const;

const profiles: Array<{ id: TrainingProfile; label: string }> = [
  { id: 'physical_joint8', label: 'Physical joint8（原生 8D）' },
  { id: 'fastwam_franka_joint8', label: 'FastWAM Franka joint8' },
];

export default function ExportsPage() {
  const { extensions, loading: capabilitiesLoading } = useStudioCapabilities();
  const consumerSmokesEnabled = extensions.includes('consumer_smokes');
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [jobs, setJobs] = useState<ExportJob[]>([]);
  const [smokes, setSmokes] = useState<ConsumerSmoke[]>([]);
  const [datasetId, setDatasetId] = useState('');
  const [selectedEpisodeIds, setSelectedEpisodeIds] = useState<number[]>([]);
  const [format, setFormat] = useState<ExportFormat>('lerobot');
  const [profile, setProfile] = useState<TrainingProfile>('physical_joint8');
  const [images, setImages] = useState(false);
  const [name, setName] = useState('dataset_v1');
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [episodesLoading, setEpisodesLoading] = useState(false);
  const [engineFilter, setEngineFilter] = useState<EngineFilter>('all');
  const [preflight, setPreflight] = useState<ExportPreflight>();
  const [preflightBusy, setPreflightBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [nextDatasets, nextJobs] = await Promise.all([
        api<Dataset[]>('/datasets'),
        api<ExportJob[]>('/exports'),
      ]);
      setDatasets(nextDatasets);
      setJobs(nextJobs);
      setDatasetId((current) => (
        nextDatasets.some((dataset) => String(dataset.id) === current)
          ? current
          : nextDatasets[0] ? String(nextDatasets[0].id) : ''
      ));
      setError(undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载失败');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // An optional model-check API must not gate the core dataset/export lists.
  const [smokesError, setSmokesError] = useState<string>();
  useEffect(() => {
    if (capabilitiesLoading || !consumerSmokesEnabled) {
      setSmokes([]);
      return;
    }
    const controller = new AbortController();
    void api<ConsumerSmoke[]>('/consumer-smokes', { signal: controller.signal })
      .then((result) => { setSmokes(result); setSmokesError(undefined); })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setSmokesError(caught instanceof Error ? caught.message : String(caught));
      });
    return () => controller.abort();
  }, [capabilitiesLoading, consumerSmokesEnabled, jobs]);

  useEffect(() => {
    let cancelled = false;
    setSelectedEpisodeIds([]);
    setPreflight(undefined);
    if (!datasetId) {
      setEpisodes([]);
      return () => { cancelled = true; };
    }
    setEpisodesLoading(true);
    void api<Episode[]>(`/episodes?dataset_id=${encodeURIComponent(datasetId)}&qa_status=accepted`)
      .then((nextEpisodes) => {
        if (!cancelled) setEpisodes(nextEpisodes);
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : 'Episode 候选集加载失败');
      })
      .finally(() => {
        if (!cancelled) setEpisodesLoading(false);
      });
    return () => { cancelled = true; };
  }, [datasetId]);

  const selected = useMemo(() => new Set(selectedEpisodeIds), [selectedEpisodeIds]);
  const orderedEpisodes = useMemo(
    () => episodes.filter((episode) => engineFilter === 'all' || episode.engine_id === engineFilter).sort((left, right) => {
      const bySession = right.session_id.localeCompare(left.session_id);
      if (bySession !== 0) return bySession;
      return (left.episode_index ?? Number.MAX_SAFE_INTEGER)
        - (right.episode_index ?? Number.MAX_SAFE_INTEGER);
    }),
    [engineFilter, episodes],
  );
  const selectedSummary = useMemo(
    () => describeEpisodeSelection(orderedEpisodes.filter((episode) => selected.has(episode.id))),
    [orderedEpisodes, selected],
  );
  const smokeByExport = useMemo(
    () => new Map(smokes.map((smoke) => [smoke.export_id, smoke])),
    [smokes],
  );

  function chooseFormat(nextFormat: ExportFormat) {
    setFormat(nextFormat);
    setPreflight(undefined);
    if (nextFormat === 'openpi_lerobot_v21') setProfile('openpi_franka_joint8');
    if (nextFormat === 'lerobot' && profile === 'openpi_franka_joint8') setProfile('physical_joint8');
  }

  function toggleEpisode(episodeId: number, checked: boolean) {
    setPreflight(undefined);
    setSelectedEpisodeIds((current) => (
      checked
        ? current.includes(episodeId) ? current : [...current, episodeId]
        : current.filter((id) => id !== episodeId)
    ));
  }

  function exportPayload() {
    return {
      dataset_id: Number(datasetId), episode_ids: selectedEpisodeIds, format,
      output_name: name,
      repo_id: (format === 'lerobot' || format === 'openpi_lerobot_v21') ? `local/${name}` : null,
      images: (format === 'lerobot' || format === 'openpi_lerobot_v21') && images,
      profile,
    };
  }

  async function runPreflight(): Promise<ExportPreflight> {
    setPreflightBusy(true);
    setError(undefined);
    try {
      const report = await api<ExportPreflight>('/exports/preflight', {
        method: 'POST', body: JSON.stringify(exportPayload()),
      });
      setPreflight(report);
      return report;
    } catch (caught) {
      setPreflight(undefined);
      throw caught;
    } finally {
      setPreflightBusy(false);
    }
  }

  async function start() {
    setBusy(true);
    setError(undefined);
    try {
      await runPreflight();
      await api('/exports', {
        method: 'POST',
        body: JSON.stringify(exportPayload()),
      });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '导出失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell current="exports">
      <div className="space-y-5">
        <div>
          <Badge variant="outline" className="mb-3">TRAINING FORMATS</Badge>
          <h1 className="text-2xl font-semibold">导出中心</h1>
          <p className="mt-1 text-sm text-muted-foreground">Accepted 是候选门槛；每次导出仍需明确选择 Episode。</p>
        </div>

        {error && <div className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive">{error}</div>}

        <div className="grid gap-3 md:grid-cols-4">
          {formats.map((item) => {
            const Icon = item.icon;
            const active = format === item.id;
            return (
              <button
                key={item.id}
                onClick={() => chooseFormat(item.id)}
                className={`rounded-xl border p-4 text-left transition-colors ${active ? 'border-primary bg-primary/8' : 'border-border/70 bg-card hover:border-primary/40'}`}
              >
                <Icon className={active ? 'size-5 text-primary' : 'size-5 text-muted-foreground'} />
                <strong className="mt-4 block">{item.title}</strong>
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">{item.note}</span>
              </button>
            );
          })}
        </div>

        <Card className="instrument-card">
          <CardHeader>
            <CardTitle>1. 选择 Dataset 与 Episodes</CardTitle>
            <CardDescription>这里只列出未回收 session 中 QA accepted 的 Episode。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="max-w-xl space-y-2">
              <Label>Dataset</Label>
              <NativeSelect className="w-full" value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
                {datasets.map((dataset) => (
                  <NativeSelectOption key={dataset.id} value={dataset.id}>
                    {dataset.name} · G {dataset.genesis_accepted_count} / I {dataset.isaac_accepted_count} / R {dataset.roboverse_accepted_count} accepted
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </div>
            <div className="max-w-xs space-y-2">
              <Label>Simulator</Label>
              <NativeSelect value={engineFilter} onChange={(event) => { setEngineFilter(event.target.value as EngineFilter); setSelectedEpisodeIds([]); setPreflight(undefined); }}>
                <NativeSelectOption value="all">全部 Simulator</NativeSelectOption>
                <NativeSelectOption value="genesis">Genesis only</NativeSelectOption>
                <NativeSelectOption value="isaac_sim">Isaac Sim only</NativeSelectOption>
                <NativeSelectOption value="roboverse">RoboVerse only</NativeSelectOption>
              </NativeSelect>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">已选择 {selectedEpisodeIds.length} / {orderedEpisodes.length}</Badge>
              <Button type="button" size="sm" variant="outline" disabled={!orderedEpisodes.length} onClick={() => { setSelectedEpisodeIds(orderedEpisodes.map((episode) => episode.id)); setPreflight(undefined); }}>全选当前 Simulator</Button>
              <Button type="button" size="sm" variant="ghost" disabled={!selectedEpisodeIds.length} onClick={() => { setSelectedEpisodeIds([]); setPreflight(undefined); }}>清空</Button>
            </div>
            {selectedEpisodeIds.length > 0 && (
              <div className="rounded-lg border border-primary/25 bg-primary/5 px-3 py-2 font-mono text-xs leading-5">
                {selectedSummary}
              </div>
            )}
            <Table>
              <TableHeader>
                <TableRow><TableHead>选择</TableHead><TableHead>Session</TableHead><TableHead>Episode</TableHead><TableHead>Task</TableHead><TableHead>时长</TableHead><TableHead>结果</TableHead><TableHead>采集时间</TableHead><TableHead /></TableRow>
              </TableHeader>
              <TableBody>
                {orderedEpisodes.map((episode) => (
                  <TableRow key={episode.id}>
                    <TableCell><Checkbox checked={selected.has(episode.id)} onCheckedChange={(checked) => toggleEpisode(episode.id, checked)} aria-label={`选择 ${episode.episode_uuid}`} /></TableCell>
                    <TableCell><p className="text-xs">{formatSessionTime(episode.session_id)}</p><p className="text-xs text-muted-foreground">{engineLabel(episode.engine_id)} · {episode.scene_id} · {episode.control_mode} · seed {episode.seed ?? 'N/A'}</p></TableCell>
                    <TableCell><p className="font-mono font-semibold">{formatEpisodeNumber(episode.episode_index)}</p><p className="font-mono text-[10px] text-muted-foreground">{episode.episode_uuid.slice(0, 12)}</p></TableCell>
                    <TableCell className="max-w-sm whitespace-normal">{episode.task}</TableCell>
                    <TableCell className="font-mono text-xs"><p>{formatDuration(episode.duration_s)}</p><p className="text-muted-foreground">{episode.num_frames} frames · {episode.fps ?? 'N/A'} Hz</p></TableCell>
                    <TableCell className="text-xs">operator: {resultLabel(episode.operator_success)}<br />auto: {resultLabel(episode.auto_success)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{formatChinaTime(episode.created_at)}</TableCell>
                    <TableCell><Button size="sm" variant="ghost" render={<a href={`/episodes/${episode.id}`} target="_blank" rel="noreferrer" />}>查看 QA</Button></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {!episodesLoading && !episodes.length && <p className="py-8 text-center text-sm text-muted-foreground">这个 Dataset 当前没有可导出的 accepted Episode。</p>}
            {episodesLoading && <p className="py-8 text-center text-sm text-muted-foreground">正在加载候选 Episode…</p>}
          </CardContent>
        </Card>

        <Card className="instrument-card">
          <CardHeader>
            <CardTitle>2. 配置并提交</CardTitle>
            <CardDescription>选择范围和训练视图会随任务保存，原始 Episode 不会改变。</CardDescription>
          </CardHeader>
          <CardContent className="grid items-end gap-4 md:grid-cols-[1fr_1fr_1fr_auto]">
            {format === 'lerobot' && <div className="space-y-2"><Label>Training profile</Label><NativeSelect className="w-full" value={profile} onChange={(event) => { setProfile(event.target.value as TrainingProfile); setPreflight(undefined); }}>{profiles.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.label}</NativeSelectOption>)}</NativeSelect></div>}
            {format === 'openpi_lerobot_v21' && <div className="space-y-2"><Label>Training profile</Label><Input value="OpenPI Franka joint8（固定）" disabled /></div>}
            <div className="space-y-2"><Label>输出名称</Label><Input value={name} onChange={(event) => { setName(event.target.value); setPreflight(undefined); }} /><p className="text-xs text-muted-foreground">推荐：profile_scene_seed_split_count_date</p></div>
            {(format === 'lerobot' || format === 'openpi_lerobot_v21') && <label className="flex h-8 items-center gap-2 text-sm"><Checkbox checked={images} onCheckedChange={(checked) => { setImages(checked); setPreflight(undefined); }} />保存图片而不是 MP4</label>}
            <div className="flex gap-2"><Button variant="outline" disabled={preflightBusy || !datasetId || !name || selectedEpisodeIds.length === 0} onClick={() => void runPreflight().catch((caught: unknown) => setError(caught instanceof Error ? caught.message : '预检失败'))}><ShieldCheck />{preflightBusy ? '检查中…' : '兼容性预检'}</Button><Button disabled={busy || !datasetId || !name || selectedEpisodeIds.length === 0} onClick={start}>{busy ? '提交中…' : `导出 ${selectedEpisodeIds.length} 条 ${format}`}</Button></div>
          </CardContent>
        </Card>

        {preflight && <Card className="instrument-card border-emerald-500/30"><CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4 text-emerald-500" />预检通过</CardTitle><CardDescription>{preflight.episode_count} Episodes · {Object.entries(preflight.engine_counts).map(([engine, count]) => `${engineLabel(engine)} ${count}`).join(' · ')}</CardDescription></CardHeader><CardContent className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4"><PreflightItem label="Robot / FPS" value={`${preflight.robot_id} · ${preflight.fps} Hz`} /><PreflightItem label="Action" value={`${preflight.action_profile} → ${preflight.training_profile}`} /><PreflightItem label="Cameras" value={preflight.camera_names.join(', ') || 'none'} /><PreflightItem label="Optional observations" value={preflight.optional_observations.join(', ') || 'none'} />{preflight.warnings.map((warning) => <p key={warning} className="col-span-full text-amber-600">• {warning}</p>)}</CardContent></Card>}

        <Card className="instrument-card">
          <CardHeader><CardTitle>任务记录</CardTitle><CardDescription>失败记录会保留；新任务同时记录 Episode 范围和训练 profile。</CardDescription></CardHeader>
          <CardContent>
            {consumerSmokesEnabled && smokesError && <p role="alert" className="mb-3 text-sm text-destructive">模型检查记录加载失败：{smokesError}</p>}
            <Table>
              <TableHeader><TableRow><TableHead>Job</TableHead><TableHead>Format / Profile</TableHead><TableHead>Episodes</TableHead><TableHead>Export</TableHead>{consumerSmokesEnabled && <TableHead>Consumer smoke</TableHead>}<TableHead>Output</TableHead><TableHead><Button variant="ghost" size="sm" onClick={load}><RefreshCw /></Button></TableHead></TableRow></TableHeader>
              <TableBody>{jobs.map((job) => { const smoke = smokeByExport.get(job.id); const weight = smoke?.report?.weight_forward; const engines = [...new Set(job.episode_refs.map((item) => item.engine_id).filter(Boolean))]; return <TableRow key={job.id}><TableCell className="font-mono text-xs">{job.id}</TableCell><TableCell>{job.format}<p className="text-xs text-muted-foreground">{job.profile ?? 'legacy job'}</p></TableCell><TableCell><p className="font-mono text-xs">{describeExportSelection(job.episode_refs)}</p><p className="mt-1 text-xs text-muted-foreground">{job.episode_count} 条 · {engines.map(engineLabel).join(' + ') || 'legacy provenance'}</p></TableCell><TableCell><Badge variant={job.status === 'completed' ? 'default' : 'outline'}>{job.status}</Badge></TableCell>{consumerSmokesEnabled && <TableCell>{smoke ? <><Badge variant={smoke.status === 'passed' ? 'default' : 'outline'}>{smoke.consumer}: {smoke.status}</Badge>{weight && <div className="mt-1 text-xs"><p>weights: {weight.weights_loaded ? 'loaded' : 'failed'} · forward: {weight.model_forward_passed ? 'passed' : 'failed'}</p><p className={weight.deployment_compatible ? 'text-emerald-600' : 'text-amber-600'}>deployment: {weight.deployment_compatible ? 'compatible' : 'contract mismatch'}</p></div>}<p className="mt-1 max-w-56 truncate font-mono text-xs text-muted-foreground" title={smoke.report_path}>{smoke.report_path}</p><p className="text-xs text-destructive">{smoke.error ?? smoke.report_read_error}</p></> : <span className="text-xs text-muted-foreground">N/A</span>}</TableCell>}<TableCell className="max-w-sm truncate font-mono text-xs">{job.output_path}</TableCell><TableCell className="text-xs text-destructive">{job.error}</TableCell></TableRow>; })}</TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

function formatEpisodeNumber(index: number | null): string {
  return index == null ? '#??????' : `#${String(index).padStart(6, '0')}`;
}

function formatDuration(value: number | null): string {
  return value == null ? 'N/A' : `${value.toFixed(1)} s`;
}

function formatSessionTime(sessionId: string): string {
  const match = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})\+0800_/.exec(sessionId);
  if (!match) return sessionId;
  return `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}:${match[6]} · ${sessionId.slice(-8)}`;
}

function compactEpisodeIndices(indices: Array<number | null>): string {
  const values = [...new Set(indices.filter((value): value is number => value != null))].sort((a, b) => a - b);
  const ranges: string[] = [];
  let start = values[0];
  let end = values[0];
  for (const value of values.slice(1)) {
    if (end != null && value === end + 1) {
      end = value;
      continue;
    }
    if (start != null && end != null) ranges.push(start === end ? formatEpisodeNumber(start) : `${formatEpisodeNumber(start)}–${formatEpisodeNumber(end)}`);
    start = end = value;
  }
  if (start != null && end != null) ranges.push(start === end ? formatEpisodeNumber(start) : `${formatEpisodeNumber(start)}–${formatEpisodeNumber(end)}`);
  const unknown = indices.length - values.length;
  if (unknown > 0) ranges.push(`${unknown} 条未编号`);
  return ranges.join(', ') || '无';
}

function describeIndexedSelection(items: Array<{ session_id: string; episode_index: number | null }>): string {
  if (items.length === 0) return 'N/A';
  const bySession = new Map<string, Array<number | null>>();
  for (const item of items) {
    const indices = bySession.get(item.session_id) ?? [];
    indices.push(item.episode_index);
    bySession.set(item.session_id, indices);
  }
  if (bySession.size === 1) return compactEpisodeIndices([...bySession.values()][0] ?? []);
  return [...bySession.entries()]
    .map(([sessionId, indices]) => `${formatSessionTime(sessionId)}: ${compactEpisodeIndices(indices)}`)
    .join(' · ');
}

function describeEpisodeSelection(episodes: Episode[]): string {
  return describeIndexedSelection(episodes);
}

function describeExportSelection(references: ExportEpisodeRef[]): string {
  return describeIndexedSelection(references);
}

function resultLabel(value: number | null): string {
  return value == null ? 'N/A' : value ? 'success' : 'failure';
}

function PreflightItem({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-border/70 p-3"><p className="text-muted-foreground">{label}</p><p className="mt-1 break-all font-mono">{value}</p></div>;
}

function formatChinaTime(value: string | null): string {
  if (!value) return 'N/A';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date);
}
