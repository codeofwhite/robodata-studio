'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { MouseEvent } from 'react';
import { Check, Database, RefreshCw, X } from 'lucide-react';

import { AppShell } from '@/components/app-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api, API_BASE } from '@/lib/api';
import { engineLabel } from '@/lib/engines';
import type { Dataset, Episode } from '@/lib/types';

type RenderJob = { session_id: string; status: string; episode_id: number | null; progress?: {frame?: number; total?: number}; error?: string | null };
type RenderState = { availability: {available: boolean; reason?: string}; jobs: RenderJob[] };

type QaFilter = 'all' | 'pending' | 'accepted' | 'rejected';
type EngineFilter = 'all' | 'genesis' | 'isaac_sim' | 'roboverse';

export default function EpisodesPage() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [qaFilter, setQaFilter] = useState<QaFilter>('all');
  const [engineFilter, setEngineFilter] = useState<EngineFilter>('all');
  const [datasetId, setDatasetId] = useState('all');
  const [sessionId, setSessionId] = useState<string>();
  const [page, setPage] = useState(1);
  // 0 表示不分页
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(true);
  const [qaBusy, setQaBusy] = useState<number | null>(null);
  const [error, setError] = useState<string>();
  const [renderEpisode, setRenderEpisode] = useState<Episode>();
  const [renderState, setRenderState] = useState<RenderState>();
  const [renderGpu, setRenderGpu] = useState(0);
  const [renderBusy, setRenderBusy] = useState(false);
  const [renderError, setRenderError] = useState<string>();

  useEffect(() => {
    if (!renderEpisode) return;
    let cancelled = false;
    setRenderState(undefined);setRenderError(undefined);
    const refresh = () => void api<RenderState>(`/episodes/${renderEpisode.id}/isaac-render`)
      .then(value => {if (!cancelled) setRenderState(value);})
      .catch(e => {if (!cancelled) setRenderError(String(e));});
    refresh();const timer = setInterval(refresh, 2000);
    document.getElementById('isaac-render-panel')?.scrollIntoView({behavior:'smooth',block:'start'});
    return () => {cancelled=true;clearInterval(timer);};
  }, [renderEpisode]);

  async function startRender() {
    if (!renderEpisode) return;
    setRenderBusy(true);setRenderError(undefined);
    try {
      await api(`/episodes/${renderEpisode.id}/isaac-render`, {method:'POST',body:JSON.stringify({gpu:renderGpu})});
      setRenderState(await api<RenderState>(`/episodes/${renderEpisode.id}/isaac-render`));
    } catch (e) {setRenderError(e instanceof Error ? e.message : String(e));}
    finally {setRenderBusy(false);}
  }


  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setSessionId(params.get('session') ?? undefined);
    const requestedEngine = params.get('engine');
    if (requestedEngine === 'genesis' || requestedEngine === 'isaac_sim' || requestedEngine === 'roboverse') setEngineFilter(requestedEngine);
    const requestedQa = params.get('qa');
    if (requestedQa === 'pending' || requestedQa === 'accepted' || requestedQa === 'rejected') setQaFilter(requestedQa);
    const requestedDataset = params.get('dataset');
    if (requestedDataset) setDatasetId(requestedDataset);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams();
      if (sessionId) query.set('session_id', sessionId);
      if (!sessionId && datasetId !== 'all') query.set('dataset_id', datasetId);
      if (qaFilter !== 'all') query.set('qa_status', qaFilter);
      if (engineFilter !== 'all') query.set('engine_id', engineFilter);
      const [nextEpisodes, nextDatasets] = await Promise.all([
        api<Episode[]>(`/episodes?${query}`),
        api<Dataset[]>('/datasets'),
      ]);
      setEpisodes(nextEpisodes);
      setDatasets(nextDatasets);
      setError(undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [datasetId, engineFilter, qaFilter, sessionId]);

  useEffect(() => { void load(); }, [load]);

  const qaCounts = useMemo(() => ({
    pending: episodes.filter((episode) => episode.qa_status === 'pending').length,
    accepted: episodes.filter((episode) => episode.qa_status === 'accepted').length,
    rejected: episodes.filter((episode) => episode.qa_status === 'rejected').length,
  }), [episodes]);

  // 审核会让列表变短，所以在渲染时夹住页码，避免越界那一帧渲出空表
  const effectivePageSize = pageSize > 0 ? pageSize : Math.max(episodes.length, 1);
  const pageCount = Math.max(1, Math.ceil(episodes.length / effectivePageSize));
  const currentPage = Math.min(page, pageCount);
  const pageRows = episodes.slice(
    (currentPage - 1) * effectivePageSize,
    currentPage * effectivePageSize,
  );

  async function decide(event: MouseEvent, episode: Episode, qaStatus: 'accepted' | 'rejected') {
    event.stopPropagation();
    setQaBusy(episode.id);
    try {
      await api(`/episodes/${episode.id}/qa`, {
        method: 'PATCH',
        body: JSON.stringify({
          qa_status: qaStatus,
          failure_reason: qaStatus === 'rejected' ? episode.failure_reason ?? 'quick_reject' : null,
        }),
      });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'QA 更新失败');
    } finally {
      setQaBusy(null);
    }
  }

  return (
    <AppShell current="episodes">
      <div className="space-y-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <Badge variant="outline" className="mb-3">DATASET QA</Badge>
            <h1 className="text-2xl font-semibold">Episodes</h1>
            <p className="mt-1 text-sm text-muted-foreground">Genesis 原生采集后，可选择 Episode 交给 Isaac 离线渲染；原始状态、动作和数据保持不变。</p>
          </div>
          <Button variant="outline" onClick={load}><RefreshCw className={loading ? 'animate-spin' : ''} />刷新</Button>
        </div>

        {error && <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>}

        {renderEpisode && <Card id="isaac-render-panel"><CardHeader><CardTitle>Isaac 离线渲染 · Episode #{renderEpisode.id}</CardTitle><CardDescription>读取已保存的状态生成 RGB，不重新计算物理。结果作为独立派生 Episode，重新进入 QA。</CardDescription></CardHeader><CardContent className="space-y-3">
          {!renderState && !renderError && <p>正在检查源数据…</p>}
          {renderState && !renderState.availability.available && <p className="text-sm text-amber-600">{renderState.availability.reason}</p>}
          <div className="flex flex-wrap items-center gap-3"><label className="text-sm">渲染 GPU <input aria-label="渲染 GPU" type="number" min={0} max={255} className="ml-2 w-20 rounded border bg-background p-2" value={renderGpu} onChange={e=>setRenderGpu(Number(e.target.value))} /></label><Button disabled={renderBusy || !renderState?.availability.available || !Number.isInteger(renderGpu) || renderGpu<0 || renderGpu>255 || renderState.jobs.some(j=>['starting','running','stopping'].includes(j.status))} onClick={()=>void startRender()}>{renderBusy?'提交中…':'开始 Isaac 离线渲染'}</Button><Button variant="ghost" onClick={()=>setRenderEpisode(undefined)}>关闭</Button></div>
          {renderError && <p className="text-sm text-destructive">{renderError}</p>}
          {renderState?.jobs.map(job=><div key={job.session_id} className="space-y-2 rounded border p-3"><p className="text-sm">{{starting:'初始化',running:'渲染中',rendering:'渲染中',completed:'已完成',failed:'失败',stopping:'停止中',stopped:'已停止',not_managed:'等待启动'}[job.status] ?? job.status} {job.progress?.total?` · ${job.progress.frame ?? 0} / ${job.progress.total} 帧`:''}</p>{job.error && <p className="text-sm text-destructive">渲染未完成，原始 Episode 未修改。</p>}<a className="text-xs text-muted-foreground underline" href={`/sessions/${job.session_id}`}>任务详情与日志</a>{job.episode_id && <><a className="text-sm text-primary underline" href={`/episodes/${job.episode_id}`}>查看派生 Episode 与逐帧预览</a><img alt="Isaac 渲染首帧" className="max-w-sm rounded" src={`${API_BASE}/episodes/${job.episode_id}/frames/base/0`} /></>}</div>)}
        </CardContent></Card>}

        <Card className="instrument-card">
          <CardHeader>
            <CardTitle>Episode 索引</CardTitle>
            <CardDescription>
              {sessionId ? `Session 队列：${sessionId}` : `${episodes.length} 条记录`} · 待判 {qaCounts.pending} · 已接受 {qaCounts.accepted} · 已拒绝 {qaCounts.rejected}
              <br />这是一个 QA 审核队列：每行的 Accept / Reject 会直接写回该 Episode 的 qa_status。
            </CardDescription>
            <div className="grid gap-2 pt-2 sm:grid-cols-3">
              <NativeSelect value={datasetId} disabled={Boolean(sessionId)} onChange={(event) => { setDatasetId(event.target.value); setPage(1); }}>
                <NativeSelectOption value="all">全部 Dataset</NativeSelectOption>
                {datasets.map((dataset) => <NativeSelectOption key={dataset.id} value={dataset.id}>{dataset.name}</NativeSelectOption>)}
              </NativeSelect>
              <NativeSelect value={engineFilter} onChange={(event) => { setEngineFilter(event.target.value as EngineFilter); setPage(1); }}>
                <NativeSelectOption value="all">全部 Simulator</NativeSelectOption>
                <NativeSelectOption value="genesis">Genesis</NativeSelectOption>
                <NativeSelectOption value="isaac_sim">Isaac Sim</NativeSelectOption>
                <NativeSelectOption value="roboverse">RoboVerse</NativeSelectOption>
              </NativeSelect>
              <NativeSelect value={qaFilter} onChange={(event) => { setQaFilter(event.target.value as QaFilter); setPage(1); }}>
                <NativeSelectOption value="all">全部 QA 状态</NativeSelectOption>
                <NativeSelectOption value="pending">Pending</NativeSelectOption>
                <NativeSelectOption value="accepted">Accepted</NativeSelectOption>
                <NativeSelectOption value="rejected">Rejected</NativeSelectOption>
              </NativeSelect>
            </div>
          </CardHeader>
          <CardContent className="px-2 sm:px-4">
            {!loading && episodes.length === 0 ? (
              <Empty><EmptyHeader><EmptyMedia variant="icon"><Database /></EmptyMedia><EmptyTitle>当前队列没有 Episode</EmptyTitle><EmptyDescription>调整筛选条件，或在会话页扫描采集目录。</EmptyDescription></EmptyHeader><EmptyContent><Button render={<a href="/sessions/new" />}>新建采集会话</Button></EmptyContent></Empty>
            ) : (
              <Table>
                <TableHeader><TableRow><TableHead>Episode</TableHead><TableHead>来源</TableHead><TableHead>任务</TableHead><TableHead>时长</TableHead><TableHead>结果</TableHead><TableHead>QA 与操作</TableHead></TableRow></TableHeader>
                <TableBody>{pageRows.map((episode) => (
                  <TableRow key={episode.id} className="cursor-pointer" onClick={() => { window.location.href = `/episodes/${episode.id}`; }}>
                    <TableCell><p className="font-mono text-xs font-semibold">#{String(episode.episode_index ?? '?').padStart(6, '0')}</p><p className="font-mono text-[10px] text-muted-foreground">DB {episode.id} · {episode.episode_uuid.slice(0, 12)}</p><p className="font-mono text-[10px] text-muted-foreground">session …{episode.session_id.slice(-8)}</p></TableCell>
                    <TableCell><Badge variant="outline">{engineLabel(episode.engine_id)}</Badge>{episode.worker_id === 'isaac_offline_episode_renderer' && <Badge variant="outline" className="ml-1">Isaac 离线渲染</Badge>}<p className="mt-1 text-[11px] text-muted-foreground">{episode.scene_id} · {episode.control_mode}</p><p className="font-mono text-[10px] text-muted-foreground">{episode.engine_version ?? 'version N/A'}</p></TableCell>
                    <TableCell><p className="text-xs">{episode.task}</p><p className="font-mono text-[10px] text-muted-foreground">{episode.source_trajectory ?? '—'} · seed {episode.seed ?? '—'}</p>{episode.is_duplicate && <Badge variant="destructive" className="mt-1">DUPLICATE ×{episode.duplicate_group_size}</Badge>}</TableCell>
                    <TableCell className="font-mono text-xs">{episode.num_frames} 帧<br /><span className="text-muted-foreground">{episode.duration_s?.toFixed(1) ?? 'N/A'} s</span></TableCell>
                    <TableCell><p className="text-[11px]"><span className="text-muted-foreground">Operator </span><Result value={episode.operator_success == null ? null : Boolean(episode.operator_success)} /></p><p className="mt-1 text-[11px]"><span className="text-muted-foreground">Auto </span><Result value={episode.auto_success == null ? null : Boolean(episode.auto_success)} /></p></TableCell>
                    <TableCell><div className="flex flex-col gap-2"><Badge variant={episode.qa_status === 'accepted' ? 'default' : 'outline'}>{episode.qa_status}</Badge><div className="flex gap-1"><Button size="sm" disabled={qaBusy === episode.id || episode.qa_status === 'accepted'} onClick={(event) => void decide(event, episode, 'accepted')}><Check />Accept</Button><Button size="sm" variant="outline" disabled={qaBusy === episode.id || episode.qa_status === 'rejected'} onClick={(event) => void decide(event, episode, 'rejected')}><X />Reject</Button></div>{episode.engine_id === 'genesis' && episode.worker_id !== 'isaac_offline_episode_renderer' && <Button size="sm" variant="outline" onClick={event=>{event.stopPropagation();setRenderEpisode(episode);}}>Isaac 离线渲染</Button>}</div></TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            )}
            {episodes.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-muted-foreground">第 {currentPage} / {pageCount} 页 · 本页 {pageRows.length} 条</p>
                <div className="flex items-center gap-2">
                  <NativeSelect size="sm" className="w-28" value={String(pageSize)} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}>
                    <NativeSelectOption value="20">每页 20 条</NativeSelectOption>
                    <NativeSelectOption value="50">每页 50 条</NativeSelectOption>
                    <NativeSelectOption value="0">显示全部</NativeSelectOption>
                  </NativeSelect>
                  <Button size="sm" variant="outline" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>上一页</Button>
                  <Button size="sm" variant="outline" disabled={currentPage >= pageCount} onClick={() => setPage(currentPage + 1)}>下一页</Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

function Result({ value }: { value: boolean | null }) {
  return <span className={value == null ? 'text-xs text-muted-foreground' : value ? 'metric-ok text-xs' : 'metric-danger text-xs'}>{value == null ? 'N/A' : value ? 'SUCCESS' : 'FAILURE'}</span>;
}
