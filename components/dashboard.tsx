'use client';

import { useEffect, useState } from 'react';
import { ArrowRight, Bot, CircleGauge, Database, HardDrive, Play, Radio, TriangleAlert } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress, ProgressLabel, ProgressValue } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api, bytes } from '@/lib/api';
import { engineLabel } from '@/lib/engines';
import type { Episode, Session } from '@/lib/types';

type Health = {
  status: string;
  engines: Array<{ id: string; label: string; available: boolean }>;
  disk: { free_bytes: number; total_bytes: number; root: string };
  gpu: { available: boolean; devices: string[]; detail: string | null };
};

export function Dashboard() {
  const [health, setHealth] = useState<Health>();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [active, setActive] = useState<Session>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [nextHealth, nextSessions, nextEpisodes] = await Promise.all([
          api<Health>('/health'), api<Session[]>('/sessions'), api<Episode[]>('/episodes'),
        ]);
        const candidate = nextSessions.find((item) => ['running', 'starting'].includes(item.status)) ?? nextSessions[0];
        const detail = candidate ? await api<Session>(`/sessions/${candidate.id}`) : undefined;
        if (!cancelled) {
          setHealth(nextHealth); setSessions(nextSessions); setEpisodes(nextEpisodes); setActive(detail); setError(undefined);
        }
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : '后端不可用');
      }
    }
    void load();
    const timer = window.setInterval(load, 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const accepted = episodes.filter((item) => item.qa_status === 'accepted').length;
  const pending = episodes.filter((item) => item.qa_status === 'pending').length;
  const count = active?.episode_count ?? 0;
  const target = active?.target_episodes ?? 1;
  const readyEngines = health?.engines.filter((item) => item.available) ?? [];

  return (
    <div className="space-y-6">
      <section className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div><div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[.16em] text-primary"><Radio className="size-3.5" /> Operations overview</div><h1 className="text-2xl font-semibold tracking-tight md:text-3xl">仿真数据采集工作台</h1><p className="mt-2 max-w-2xl text-sm text-muted-foreground">统一管理隔离的 Engine Worker、Episode provenance、QA 与训练格式导出。</p></div>
        <Button size="lg" render={<a href="/sessions/new" />}><Play />新建采集会话</Button>
      </section>

      {error && <Alert variant="destructive"><TriangleAlert /><AlertTitle>Backend offline</AlertTitle><AlertDescription>{error}。先启动 8010 端口的 API；页面会自动重试。</AlertDescription></Alert>}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {!health && !error ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-28" />) : <>
          <HealthCard icon={Radio} label="Collector API" value={health ? 'Online' : 'Offline'} note="127.0.0.1:8010" ok={Boolean(health)} />
          <HealthCard icon={CircleGauge} label="GPU" value={health?.gpu.available ? `${health.gpu.devices.length} visible` : 'Unavailable'} note={health?.gpu.devices[0] ?? health?.gpu.detail ?? '等待检测'} ok={Boolean(health?.gpu.available)} />
          <HealthCard icon={HardDrive} label="Dataset disk" value={health ? `${bytes(health.disk.free_bytes)} free` : 'Unknown'} note={health?.disk.root ?? '—'} ok={Boolean(health)} />
          <HealthCard icon={Bot} label="Engine workers" value={`${readyEngines.length} / ${health?.engines.length ?? 0} Ready`} note={health?.engines.map((item) => `${item.label}: ${item.available ? 'ready' : 'missing'}`).join(' · ') ?? '—'} ok={readyEngines.length > 0} />
        </>}
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.45fr_.75fr]">
        <Card className="instrument-card"><CardHeader className="border-b border-border/70"><CardTitle className="flex items-center gap-2"><Radio className="size-4 text-primary" />{active ? '最近会话' : '尚无会话'}</CardTitle><CardDescription>{active ? `${active.dataset_name} · ${engineLabel(active.engine_id)} · ${active.control_mode.toUpperCase()} · ${active.scene_id}` : '创建第一个可追踪的采集会话'}</CardDescription>{active && <CardAction><Badge variant="outline">{active.status.toUpperCase()}</Badge></CardAction>}</CardHeader><CardContent className="space-y-5">{active ? <><div className="grid gap-3 sm:grid-cols-3"><Metric label="完成" value={`${count} / ${target}`} detail={`${Math.round(count / target * 100)}%`} /><Metric label="Accepted" value={active.accepted_count ?? 0} detail="人工 QA" tone="ok" /><Metric label="待质检" value={active.pending_count ?? 0} detail="需要处理" tone="warn" /></div><Progress value={Math.min(100, count / target * 100)}><ProgressLabel>Session progress</ProgressLabel><ProgressValue>{() => `${count} / ${target}`}</ProgressValue></Progress><div className="flex gap-2"><Button render={<a href={`/sessions/${active.id}`} />}>进入会话 <ArrowRight /></Button><Button variant="outline" render={<a href={`/episodes?session=${active.id}&engine=${active.engine_id}`} />}>查看 Episodes</Button></div></> : <div className="py-10 text-center"><Database className="mx-auto mb-3 size-6 text-muted-foreground" /><p className="text-sm text-muted-foreground">会话创建后会在这里显示实时进度。</p><Button className="mt-4" render={<a href="/sessions/new" />}>开始配置</Button></div>}</CardContent></Card>
        <Card className="instrument-card"><CardHeader><CardTitle>数据总览</CardTitle><CardDescription>当前 SQLite 索引</CardDescription></CardHeader><CardContent className="space-y-3"><Metric label="Sessions" value={sessions.length} detail="本地会话" /><Metric label="Accepted" value={accepted} detail="可进入默认导出" tone="ok" /><Metric label="Pending QA" value={pending} detail="尚未审核" tone="warn" /></CardContent></Card>
      </section>

      <Card className="instrument-card"><CardHeader><CardTitle>最近 Episode</CardTitle><CardDescription>每条数据明确显示来源 Simulator</CardDescription><CardAction><Button variant="ghost" size="sm" render={<a href="/episodes" />}>全部 <ArrowRight /></Button></CardAction></CardHeader><CardContent className="px-2 sm:px-4">{episodes.length ? <Table><TableHeader><TableRow><TableHead>Episode</TableHead><TableHead>Simulator</TableHead><TableHead>Task</TableHead><TableHead>Frames</TableHead><TableHead>Auto</TableHead><TableHead>QA</TableHead></TableRow></TableHeader><TableBody>{episodes.slice(0, 5).map((episode) => <TableRow key={episode.id}><TableCell><a className="font-mono text-xs hover:text-primary" href={`/episodes/${episode.id}`}>{episode.episode_uuid.slice(0, 12)}</a></TableCell><TableCell><Badge variant="outline">{engineLabel(episode.engine_id)}</Badge></TableCell><TableCell>{episode.task}</TableCell><TableCell className="font-mono">{episode.num_frames}</TableCell><TableCell className={episode.auto_success == null ? 'text-muted-foreground' : episode.auto_success ? 'metric-ok' : 'metric-danger'}>{episode.auto_success == null ? 'N/A' : episode.auto_success ? 'SUCCESS' : 'FAILURE'}</TableCell><TableCell><Badge variant="outline">{episode.qa_status}</Badge></TableCell></TableRow>)}</TableBody></Table> : <p className="py-10 text-center text-sm text-muted-foreground">暂无 Episode。采集完成后在会话页点击“扫描 Episodes”。</p>}</CardContent></Card>
    </div>
  );
}

function HealthCard({ icon: Icon, label, value, note, ok }: { icon: typeof Radio; label: string; value: string; note: string; ok: boolean }) {
  return <Card size="sm" className="instrument-card"><CardHeader><CardDescription>{label}</CardDescription><CardAction><span className={`status-led status-led-${ok ? 'ok' : 'warn'}`} /></CardAction><CardTitle className="flex items-center gap-2 text-lg"><Icon className="size-4 text-muted-foreground" />{value}</CardTitle></CardHeader><CardContent className="truncate font-mono text-xs text-muted-foreground" title={note}>{note}</CardContent></Card>;
}

function Metric({ label, value, detail, tone = 'neutral' }: { label: string; value: string | number; detail: string; tone?: 'neutral' | 'ok' | 'warn' }) {
  return <div className="rounded-lg border border-border/70 bg-background/40 p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 font-mono text-2xl font-semibold">{value}</p><p className={`mt-1 text-xs metric-${tone}`}>{detail}</p></div>;
}
