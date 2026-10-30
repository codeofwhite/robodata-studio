'use client';

import { Fragment, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Play, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api, API_BASE } from '@/lib/api';
import { assetHref, outcomeLabel, type EngineValidation, type ValidationOverviewResponse, type ValidationRow, type ValidationStatus, type ValidationTrial } from '@/lib/asset-types';

const engines: Record<string, string> = { genesis: 'Genesis', isaac_sim: 'Isaac', newton: 'Newton', newton_vbd: 'Newton VBD' };
const labels: Record<ValidationStatus, string> = {
  both_passed: '两引擎通过', genesis_only: '仅 Genesis 通过', isaac_only: '仅 Isaac 通过',
  newton_only: 'Newton 重复验证通过', physics_passed: '物理通过·重复验证不足', needs_repair: '需修复', unverified: '待验证', stale: '证据失效', mixed: '评价规则不同',
};
const gates: Record<string, string> = {
  grasp_retained_at_transfer_end: '搬运结束时未夹住布料', grasp_following: '布料未跟随夹爪',
  released_settled: '释放后未稳定', carried_patch_movement: '夹持区域移动不足',
  task: '任务指标未达标', active_phase_contact: '操作阶段接触不足', strain: '拉伸超限',
  finite: '出现非有限数值', penetration: '穿透超限', fixture: '固定点漂移',
};
const readyStatuses: ValidationStatus[] = ['both_passed', 'genesis_only', 'isaac_only', 'newton_only'];
const rank: Record<ValidationStatus, number> = { newton_only: 0, physics_passed: 3, both_passed: 0, genesis_only: 1, isaac_only: 2, needs_repair: 3, stale: 4, mixed: 5, unverified: 6 };
const engineName = (id: string) => engines[id] ?? id;
const gateName = (id: string) => gates[id] ?? id;

function EngineCell({ value }: { value: EngineValidation }) {
  if (!value.total) return <span className="text-muted-foreground">未验证</span>;
  if (value.status === 'mixed') return <span className="text-amber-400">分规则查看</span>;
  const detail = value.status === 'stale' ? '证据失效' : value.status === 'insufficient' ? '待补验证' : value.status === 'passed' ? '全部通过' : '有失败';
  return <div><strong className={'font-mono text-base ' + (value.status === 'passed' ? 'text-emerald-400' : value.status === 'failed' ? 'text-rose-400' : 'text-amber-400')}>{value.passed}/{value.total}</strong><p className="mt-1 text-xs text-muted-foreground">{detail}</p></div>;
}

export function ValidationOverview({ refresh }: { refresh: number }) {
  const [data, setData] = useState<ValidationOverviewResponse>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [playing, setPlaying] = useState<{ row: ValidationRow; trial: ValidationTrial } | null>(null);
  const [videoError, setVideoError] = useState(false);

  useEffect(() => {
    const focus = new URLSearchParams(window.location.search).get('focus');
    if (focus) setQ(focus);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void api<ValidationOverviewResponse>('/assets/validation-overview', { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) { setData(result); setError(''); } })
      .catch(caught => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : '加载失败'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refresh]);

  const rows = (data?.items ?? []).filter(row => {
    const matches = (row.name + ' ' + row.asset_id + ' ' + row.tags.join(' ')).toLowerCase().includes(q.trim().toLowerCase());
    return matches && (!filter || (filter === 'ready' ? readyStatuses.includes(row.status) : row.status === filter));
  }).sort((a, b) => rank[a.status] - rank[b.status] || a.asset_id.localeCompare(b.asset_id));
  const toggle = (id: string) => setExpanded(previous => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const play = (row: ValidationRow, trial: ValidationTrial) => { setVideoError(false); setPlaying({ row, trial }); };

  return <div className="space-y-4" aria-busy={loading}>
    <div className="grid gap-3 sm:grid-cols-4">
      {[
        { title: '配置总数', count: data?.summary.configs, value: '', note: '按当前配置版本汇总' },
        { title: '至少一个引擎通过', count: data?.summary.ready, value: 'ready', note: '同一规则下至少 3 次全部通过' },
        { title: '单次物理通过', count: data?.summary.physics_checked, value: 'physics_passed', note: '已通过，但未完成同配置 3 次重复验证' },
        { title: '需要修复', count: data?.summary.needs_repair, value: 'needs_repair', note: '当前配置有物理失败记录' },
      ].map(item => <button key={item.title} aria-pressed={filter === item.value} onClick={() => setFilter(item.value)} className={'rounded-xl border p-4 text-left transition-colors ' + (filter === item.value ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/40')}>
        <span className="text-sm text-muted-foreground">{item.title}</span><strong className="my-2 block font-mono text-3xl">{item.count ?? '—'}</strong><span className="text-xs text-muted-foreground">{item.note}</span>
      </button>)}
    </div>
    {error && <div role="alert" className="rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{error}；可点击页面顶部“刷新”重试。</div>}
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><CardTitle>验证概览</CardTitle><p className="mt-2 text-sm text-muted-foreground">{data ? data.summary.validations + ' 条记录 · ' + data.summary.videos + ' 个视频 · ' + data.summary.interactive_replays + ' 个三维回放' : '正在读取验证记录…'}</p></div>
          <div className="flex flex-wrap gap-2">
            <label className="relative"><Search className="absolute left-3 top-3 size-4 text-muted-foreground" /><Input aria-label="搜索验证配置" placeholder="配置名称、编号、材料…" className="pl-9" value={q} onChange={e => setQ(e.target.value)} /></label>
            <NativeSelect aria-label="配置验证结论" value={filter} onChange={e => setFilter(e.target.value)}>
              <NativeSelectOption value="">全部配置</NativeSelectOption><NativeSelectOption value="ready">至少一个引擎通过</NativeSelectOption>
              {Object.entries(labels).map(([key, label]) => <NativeSelectOption key={key} value={key}>{label}</NativeSelectOption>)}
            </NativeSelect>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <p className="mb-4 text-xs leading-5 text-muted-foreground">通过次数 / 总次数按配置、场景与评价规则分组；单次物理通过与重复验证分开显示。回放使用保存的真实轨迹。</p>
        <Table className="min-w-[900px]"><TableHeader><TableRow><TableHead>配置 / 版本</TableHead><TableHead>Genesis</TableHead><TableHead>Isaac</TableHead><TableHead>Newton VBD</TableHead><TableHead>结论</TableHead><TableHead>主要失败原因</TableHead><TableHead>代表回放</TableHead><TableHead>记录</TableHead></TableRow></TableHeader>
          <TableBody>
            {loading && !data && <TableRow><TableCell colSpan={8} className="py-10 text-center text-muted-foreground">正在核对验证结果与证据…</TableCell></TableRow>}
            {!loading && !rows.length && <TableRow><TableCell colSpan={8} className="py-10 text-center text-muted-foreground">{error ? '验证概览暂不可用' : '没有匹配配置，可调整搜索或筛选。'}</TableCell></TableRow>}
            {rows.map(row => <Fragment key={row.asset_id}>
              <TableRow>
                <TableCell className="max-w-[250px] whitespace-normal py-4"><a className="font-medium hover:text-primary hover:underline" href={assetHref(row.asset_id, row.version)}>{row.name.replace(/ config$/, '')}</a><p className="mt-1 break-all font-mono text-[11px] text-muted-foreground">{row.asset_id} · v{row.version}</p></TableCell>
                <TableCell><EngineCell value={row.engines.genesis} /></TableCell><TableCell><EngineCell value={row.engines.isaac_sim} /></TableCell><TableCell><EngineCell value={row.engines.newton_vbd} /></TableCell>
                <TableCell><Badge variant="outline" className={readyStatuses.includes(row.status) ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' : row.status === 'needs_repair' ? 'border-rose-500/30 bg-rose-500/10 text-rose-400' : 'text-amber-400'}>{labels[row.status]}</Badge></TableCell>
                <TableCell className="max-w-[245px] whitespace-normal"><div className="space-y-1 text-xs">{row.failures.slice(0, 2).map(failure => <p key={failure.engine_id + failure.gate} title={failure.gate}>{engineName(failure.engine_id)}：{gateName(failure.gate)} <span className="text-muted-foreground">×{failure.count}</span></p>)}{!row.failures.length && <span className="text-muted-foreground">—</span>}{row.failures.length > 2 && <span className="text-muted-foreground">另有 {row.failures.length - 2} 项，展开查看</span>}</div></TableCell>
                <TableCell><div className="flex flex-col items-start gap-1">{Object.entries(row.engines).filter(([, value]) => value.representative).map(([engine, value]) => <Button key={engine} size="sm" variant="ghost" aria-label={'播放 ' + row.asset_id + ' ' + engineName(engine) + ' 代表回放'} onClick={() => value.representative && play(row, value.representative)}><Play className="size-3" />{engineName(engine)} · {outcomeLabel(value.representative?.outcome)}</Button>)}{!Object.values(row.engines).some(value => value.representative) && <span className="text-xs text-muted-foreground">暂无可用回放</span>}</div></TableCell>
                <TableCell><Button size="sm" variant="ghost" aria-label={(expanded.has(row.asset_id) ? '收起 ' : '展开 ') + row.asset_id + ' 验证记录'} aria-expanded={expanded.has(row.asset_id)} aria-controls={'trials-' + row.asset_id} onClick={() => toggle(row.asset_id)}>{expanded.has(row.asset_id) ? <ChevronDown /> : <ChevronRight />}{row.trials.length} 次</Button></TableCell>
              </TableRow>
              {expanded.has(row.asset_id) && <TableRow id={'trials-' + row.asset_id} className="bg-muted/20 hover:bg-muted/20"><TableCell colSpan={8} className="whitespace-normal p-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><strong className="text-sm">{row.name} · v{row.version} 单次记录</strong><span className="text-xs text-muted-foreground">同一验证编号的修订只计一次</span></div>
                {row.historical_count > 0 && <p className="mb-3 text-sm text-amber-400">{row.historical_count} 条验证属于其他配置版本，不计入本行；可在<a className="underline" href={assetHref(row.asset_id)}>配置版本历史</a>查看。</p>}
                {row.integrity.status === 'stale' && <p className="mb-3 break-all text-sm text-destructive">{row.integrity.issues.join('；')}</p>}
                <div className="mb-3 space-y-1 text-xs text-muted-foreground">{Object.entries(row.engines).flatMap(([engine, value]) => value.protocols.map(protocol => <p key={engine + protocol.evaluator_version + protocol.scope + protocol.scenario}>{engineName(engine)} · {protocol.evaluator_version} · {protocol.scope}{protocol.scenario ? ' · ' + protocol.scenario : ''}：{protocol.passed}/{protocol.total}</p>))}</div>
                <Table><TableHeader><TableRow><TableHead>引擎 / 运行</TableHead><TableHead>结果</TableHead><TableHead>全部失败原因</TableHead><TableHead>证据</TableHead><TableHead>回放</TableHead></TableRow></TableHeader><TableBody>
                  {!row.trials.length && <TableRow><TableCell colSpan={5} className="text-muted-foreground">当前配置版本尚无验证记录。</TableCell></TableRow>}
                  {row.trials.map(trial => <TableRow key={trial.asset_id}><TableCell><span className="mr-2 text-xs">{engineName(trial.engine_id)}</span><a className="text-primary hover:underline" href={assetHref(trial.asset_id, trial.version)}>{trial.source_trial.split('/').at(-1)}</a><p className="mt-1 font-mono text-[10px] text-muted-foreground">{trial.asset_id} · v{trial.version}</p></TableCell>
                    <TableCell><Badge variant={trial.outcome === 'failed' ? 'destructive' : 'outline'}>{outcomeLabel(trial.outcome)}</Badge></TableCell>
                    <TableCell className="max-w-[320px] whitespace-normal text-xs">{trial.failed_gates.length ? trial.failed_gates.map(gate => <p key={gate} title={gate}>{gateName(gate)}</p>) : '—'}</TableCell>
                    <TableCell className="max-w-[250px] whitespace-normal text-xs"><span className={trial.integrity.status === 'stale' ? 'text-destructive' : 'text-muted-foreground'}>{trial.integrity.status === 'current' ? '文件一致' : '证据失效'}</span>{trial.integrity.issues.length > 0 && <p className="mt-1 break-all text-destructive">{trial.integrity.issues.join('；')}</p>}</TableCell>
                    <TableCell>{(trial.video || trial.replay) && trial.integrity.status === 'current' ? <Button size="sm" variant="ghost" onClick={() => play(row, trial)}><Play />播放</Button> : <span className="text-xs text-muted-foreground">暂无可用回放</span>}</TableCell>
                  </TableRow>)}
                </TableBody></Table>
              </TableCell></TableRow>}
            </Fragment>)}
          </TableBody>
        </Table>
        <p className="mt-4 text-xs text-muted-foreground">{loading ? '正在刷新证据…' : '显示 ' + rows.length + ' / ' + (data?.summary.configs ?? 0) + ' 套配置'}{data && data.summary.unlinked_validations > 0 ? ' · ' + data.summary.unlinked_validations + ' 条验证未关联配置，可在资产索引中查看' : ''}</p>
      </CardContent>
    </Card>
    <Dialog open={playing !== null} onOpenChange={open => { if (!open) setPlaying(null); }}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader><DialogTitle>{playing?.row.name.replace(/ config$/, '')} · {playing ? engineName(playing.trial.engine_id) : ''}</DialogTitle><DialogDescription>记录轨迹回放 · 本次结果：{outcomeLabel(playing?.trial.outcome)}。代表回放仅展示这一次运行。</DialogDescription></DialogHeader>
        {playing?.trial.replay && <iframe title="三维验证回放" className="h-[540px] w-full rounded-lg border bg-slate-950" sandbox="allow-scripts" src={API_BASE + playing.trial.replay.url} />}
        {playing?.trial.video && <video key={playing.trial.video.url} aria-label="验证轨迹回放" className="max-h-[65vh] w-full rounded-lg bg-black" controls playsInline preload="metadata" src={API_BASE + playing.trial.video.url} onError={() => setVideoError(true)} />}
        {videoError && <p role="alert" className="text-sm text-destructive">视频加载失败，请刷新概览核对证据状态。</p>}
        {playing && <a className="break-all text-xs text-primary hover:underline" href={assetHref(playing.trial.asset_id, playing.trial.version)}>查看此验证记录：{playing.trial.asset_id} · v{playing.trial.version}</a>}
      </DialogContent>
    </Dialog>
  </div>;
}
