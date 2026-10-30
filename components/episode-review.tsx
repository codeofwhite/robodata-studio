'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, ChevronLeft, ImageOff, SkipForward, X } from 'lucide-react';

import { AppShell } from '@/components/app-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { Skeleton } from '@/components/ui/skeleton';
import { api, API_BASE } from '@/lib/api';
import { engineLabel } from '@/lib/engines';
import type { Episode } from '@/lib/types';

export function EpisodeReview({ episodeId }: { episodeId: number }) {
  const [episode, setEpisode] = useState<Episode>();
  const [frame, setFrame] = useState(0);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const load = useCallback(async () => {
    try {
      const next = await api<Episode>(`/episodes/${episodeId}`);
      setEpisode(next);
      setReason(next.failure_reason ?? '');
      setError(undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载失败');
    }
  }, [episodeId]);

  useEffect(() => { void load(); }, [load]);
  const cameras = episode?.manifest?.camera_names ?? [];
  const plots = useMemo(() => {
    const action = episode?.trajectory?.policy_action as number[][] | undefined;
    return action?.map((row) => row[0] ?? 0) ?? [];
  }, [episode]);

  async function decide(qaStatus: 'accepted' | 'rejected', advance: boolean) {
    if (!episode) return;
    setBusy(true);
    setError(undefined);
    try {
      await api(`/episodes/${episodeId}/qa`, {
        method: 'PATCH',
        body: JSON.stringify({
          qa_status: qaStatus,
          failure_reason: qaStatus === 'rejected' ? reason || 'qa_rejected' : null,
        }),
      });
      if (advance) {
        const queue = await api<Episode[]>(
          `/episodes?dataset_id=${episode.dataset_id}&engine_id=${episode.engine_id}&qa_status=pending`,
        );
        const next = queue.find((candidate) => candidate.id !== episode.id);
        if (next) {
          window.location.href = `/episodes/${next.id}`;
          return;
        }
        window.location.href = `/episodes?dataset=${episode.dataset_id}&engine=${episode.engine_id}&qa=pending`;
        return;
      }
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '更新失败');
    } finally {
      setBusy(false);
    }
  }

  if (!episode) return <AppShell current="episodes"><div className="space-y-4">{error && <p className="text-destructive">{error}</p>}<Skeleton className="h-12 w-72" /><Skeleton className="h-[500px] w-full" /></div></AppShell>;

  return (
    <AppShell current="episodes">
      <div className="space-y-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <a href={`/episodes?dataset=${episode.dataset_id}&engine=${episode.engine_id}`} className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ChevronLeft className="size-3.5" /> Episode 列表</a>
            <div className="flex flex-wrap items-center gap-2"><h1 className="font-mono text-xl font-semibold">{episode.episode_uuid}</h1><Badge variant="outline">{engineLabel(episode.engine_id)}</Badge><Badge>{episode.qa_status}</Badge></div>
            <p className="mt-2 text-sm text-muted-foreground">{episode.task} · {episode.num_frames} frames · {episode.manifest?.fps ?? episode.fps ?? '—'} Hz</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={busy} onClick={() => void decide('rejected', false)}><X />Reject</Button>
            <Button variant="outline" disabled={busy} onClick={() => void decide('rejected', true)}><X />Reject & next</Button>
            <Button disabled={busy} onClick={() => void decide('accepted', true)}><Check />Accept & next <SkipForward /></Button>
          </div>
        </div>

        {error && <div className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive">{error}</div>}

        <div className="grid gap-4 xl:grid-cols-[1.45fr_.55fr]">
          <div className="space-y-4">
            <Card className="instrument-card"><CardHeader><CardTitle>多视角回放</CardTitle><CardDescription>Frame {frame + 1} / {episode.num_frames}</CardDescription></CardHeader><CardContent className="space-y-4">{cameras.length ? <div className={`grid gap-2 ${cameras.length > 1 ? 'sm:grid-cols-2' : ''}`}>{cameras.map((camera) => <div key={camera} className="overflow-hidden rounded-lg border border-border/70 bg-black"><div className="border-b border-white/10 px-3 py-1.5 font-mono text-[10px] text-white/60">{camera}</div><img src={`${API_BASE}/episodes/${episode.id}/frames/${encodeURIComponent(camera)}/${frame}`} alt={`${camera} frame ${frame}`} className="aspect-[4/3] w-full object-contain" /></div>)}</div> : <div className="grid aspect-video place-items-center rounded-lg border border-dashed border-border text-muted-foreground"><div className="text-center"><ImageOff className="mx-auto mb-2 size-5" /><p className="text-sm">Manifest 未声明相机</p></div></div>}<Slider min={0} max={Math.max(0, episode.num_frames - 1)} step={1} value={[frame]} onValueChange={(values) => setFrame(typeof values === 'number' ? values : (values[0] ?? 0))} /></CardContent></Card>
            <Card className="instrument-card"><CardHeader><CardTitle>Action 快览</CardTitle><CardDescription>下采样后的第一个 policy action 维度</CardDescription></CardHeader><CardContent>{plots.length ? <div className="flex h-32 items-end gap-px overflow-hidden" aria-label="action chart">{plots.map((value, index) => <span key={index} className="min-w-px flex-1 bg-primary/70" style={{ height: `${Math.max(2, Math.min(100, 50 + value * 18))}%` }} />)}</div> : <p className="text-sm text-muted-foreground">trajectory.npz 中没有 policy_action。</p>}</CardContent></Card>
          </div>

          <div className="space-y-4">
            <Card className="instrument-card"><CardHeader><CardTitle>数据来源</CardTitle><CardDescription>训练与 QA 都以 Episode provenance 为准。</CardDescription></CardHeader><CardContent className="space-y-2 text-xs"><Provenance label="Simulator" value={engineLabel(episode.engine_id)} /><Provenance label="Engine version" value={episode.engine_version ?? 'N/A'} /><Provenance label="Worker" value={episode.worker_id ?? 'N/A'} /><Provenance label="Scene" value={episode.scene_id} /><Provenance label="Seed" value={String(episode.seed ?? 'N/A')} /><Provenance label="Control source" value={episode.control_source ?? episode.control_mode} /></CardContent></Card>
            <Card className="instrument-card"><CardHeader><CardTitle>结果分层</CardTitle><CardDescription>不要用一个 success 覆盖其他证据。</CardDescription></CardHeader><CardContent className="space-y-3"><Decision label="Operator" value={episode.operator_success == null ? null : Boolean(episode.operator_success)} /><Decision label="Automatic criterion" value={episode.auto_success == null ? null : Boolean(episode.auto_success)} /><Decision label="QA decision" text={episode.qa_status} /></CardContent></Card>
            <Card className="instrument-card"><CardHeader><CardTitle>QA 备注</CardTitle><CardDescription>Reject 时填写可搜索的失败原因。</CardDescription></CardHeader><CardContent className="space-y-3"><Label htmlFor="reason">Failure reason / note</Label><Input id="reason" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="例如 grasp_slip / occlusion" /><div className="rounded-lg border border-border/70 p-3 text-xs leading-5 text-muted-foreground">物理自动判据：{JSON.stringify(episode.manifest?.episode_metrics ?? {})}</div></CardContent></Card>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function Provenance({ label, value }: { label: string; value: string }) {
  return <div className="flex justify-between gap-3 rounded border border-border/60 px-2 py-1.5"><span className="text-muted-foreground">{label}</span><span className="break-all text-right font-mono">{value}</span></div>;
}

function Decision({ label, value, text }: { label: string; value?: boolean | null; text?: string }) {
  const display = text ?? (value == null ? 'N/A' : value ? 'SUCCESS' : 'FAILURE');
  return <div className="flex items-center justify-between rounded-lg border border-border/70 px-3 py-2"><span className="text-sm text-muted-foreground">{label}</span><strong className={`font-mono text-xs ${text || value == null ? 'text-foreground' : value ? 'metric-ok' : 'metric-danger'}`}>{display.toUpperCase()}</strong></div>;
}
