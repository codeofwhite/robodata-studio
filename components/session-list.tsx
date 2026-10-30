'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowRight, Plus, RefreshCw, RotateCcw, Trash2, TriangleAlert } from 'lucide-react';

import { AppShell } from '@/components/app-shell';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api } from '@/lib/api';
import { engineLabel } from '@/lib/engines';
import type { Session } from '@/lib/types';

type Filter = 'active' | 'all' | 'trashed';
type EngineFilter = 'all' | 'genesis' | 'isaac_sim' | 'roboverse';

export function SessionList() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [filter, setFilter] = useState<Filter>('active');
  const [engineFilter, setEngineFilter] = useState<EngineFilter>('all');
  const [page, setPage] = useState(1);
  // 0 表示不分页，列表本来就不长，留着这个选项更省事
  const [pageSize, setPageSize] = useState(12);
  const [busyId, setBusyId] = useState<string>();
  const [error, setError] = useState<string>();

  const load = useCallback(async () => {
    try {
      setSessions(await api<Session[]>('/sessions?include_trashed=true'));
      setError(undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '会话列表加载失败');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const visible = useMemo(() => sessions.filter((session) => {
    if (engineFilter !== 'all' && session.engine_id !== engineFilter) return false;
    if (filter === 'trashed') return session.status === 'trashed';
    if (filter === 'active') return session.status !== 'trashed';
    return true;
  }), [engineFilter, filter, sessions]);

  // 过滤后的列表会随着「移入回收站」变短，所以在渲染时夹住页码而不是用 effect：
  // 页码越界会先渲出一帧空表
  const effectivePageSize = pageSize > 0 ? pageSize : Math.max(visible.length, 1);
  const pageCount = Math.max(1, Math.ceil(visible.length / effectivePageSize));
  const currentPage = Math.min(page, pageCount);
  const pageRows = visible.slice(
    (currentPage - 1) * effectivePageSize,
    currentPage * effectivePageSize,
  );

  async function mutate(session: Session, action: 'trash' | 'restore' | 'delete') {
    if (action === 'trash' && !window.confirm(
      `将会话移入回收站？\n\n${session.id}\n\n原始数据不会立即永久删除。`,
    )) return;
    let body: string | undefined;
    if (action === 'delete') {
      const confirmation = window.prompt(
        `永久删除会话、Episode 索引和原始数据。此操作不可恢复。\n请输入完整 Session ID：`,
      );
      if (confirmation !== session.id) {
        if (confirmation !== null) setError('Session ID 不匹配，已取消永久删除');
        return;
      }
      const accepted = session.accepted_count ?? 0;
      if (accepted > 0 && !window.confirm(
        `该会话包含 ${accepted} 条 Accepted Episode。仍然永久删除？`,
      )) return;
      body = JSON.stringify({
        confirm_session_id: confirmation,
        delete_accepted_data: accepted > 0,
      });
    }
    setBusyId(session.id);
    setError(undefined);
    try {
      await api(
        action === 'delete' ? `/sessions/${session.id}` : `/sessions/${session.id}/${action}`,
        { method: action === 'delete' ? 'DELETE' : 'POST', body },
      );
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '会话操作失败');
    } finally {
      setBusyId(undefined);
    }
  }

  return (
    <AppShell current="sessions">
      <div className="space-y-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <Badge variant="outline" className="mb-3">SESSION MANAGEMENT</Badge>
            <h1 className="text-2xl font-semibold">采集会话</h1>
            <p className="mt-1 text-sm text-muted-foreground">按时间选择会话；回收站操作可恢复，永久删除需要完整 ID 确认。</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={load}><RefreshCw />刷新</Button>
            <Button render={<a href="/sessions/new" />}><Plus />新建会话</Button>
          </div>
        </div>

        {error && <Alert variant="destructive"><TriangleAlert /><AlertTitle>会话操作失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}

        <Card className="instrument-card">
          <CardHeader className="border-b border-border/70">
            <CardTitle>Session 列表</CardTitle>
            <CardDescription>{visible.length} / {sessions.length} 条</CardDescription>
            <div className="grid max-w-md grid-cols-2 gap-2 pt-2">
              <NativeSelect
                value={filter}
                onChange={(event) => { setFilter(event.target.value as Filter); setPage(1); }}
              >
                <NativeSelectOption value="active">当前会话</NativeSelectOption>
                <NativeSelectOption value="all">全部</NativeSelectOption>
                <NativeSelectOption value="trashed">回收站</NativeSelectOption>
              </NativeSelect>
              <NativeSelect
                value={engineFilter}
                onChange={(event) => { setEngineFilter(event.target.value as EngineFilter); setPage(1); }}
              >
                <NativeSelectOption value="all">全部 Simulator</NativeSelectOption>
                <NativeSelectOption value="genesis">Genesis</NativeSelectOption>
                <NativeSelectOption value="isaac_sim">Isaac Sim</NativeSelectOption>
                <NativeSelectOption value="roboverse">RoboVerse</NativeSelectOption>
              </NativeSelect>
            </div>
          </CardHeader>
          <CardContent className="px-2 sm:px-4">
            <Table>
              <TableHeader><TableRow><TableHead>Session</TableHead><TableHead>配置</TableHead><TableHead>Episodes</TableHead><TableHead>状态</TableHead><TableHead>操作</TableHead></TableRow></TableHeader>
              <TableBody>
                {pageRows.map((session) => {
                  const trashed = session.status === 'trashed';
                  const busy = busyId === session.id;
                  const readOnly = session.config?.imported_read_only === true;
                  return (
                    <TableRow key={session.id}>
                      <TableCell className="max-w-md">
                        <p className="break-all font-mono text-xs font-semibold">{session.id}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{formatChinaTime(session.created_at)}</p>
                      </TableCell>
                      <TableCell className="text-xs">
                        <p>{session.dataset_name ?? `Dataset ${session.dataset_id}`}</p>
                        <p className="text-muted-foreground">{engineLabel(session.engine_id)} · {session.scene_id} · {session.control_mode}</p>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        <p>{session.episode_count ?? 0} total</p>
                        <p className="text-muted-foreground">{session.accepted_count ?? 0} accepted · {session.pending_count ?? 0} pending</p>
                      </TableCell>
                      <TableCell><Badge variant={session.status === 'running' ? 'default' : 'outline'}>{session.status}</Badge></TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-2">
                          {!trashed && <Button size="sm" render={<a href={`/sessions/${session.id}`} />}>打开 <ArrowRight /></Button>}
                          {!trashed && readOnly && <Badge variant="outline">只读证据</Badge>}
                          {!trashed && !readOnly && <Button size="sm" variant="outline" disabled={busy} onClick={() => mutate(session, 'trash')}><Trash2 />移入回收站</Button>}
                          {trashed && <Button size="sm" variant="outline" disabled={busy} onClick={() => mutate(session, 'restore')}><RotateCcw />恢复</Button>}
                          {trashed && <Button size="sm" variant="destructive" disabled={busy} onClick={() => mutate(session, 'delete')}><Trash2 />永久删除</Button>}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            {!visible.length && <p className="py-12 text-center text-sm text-muted-foreground">当前筛选下没有 Session。</p>}
            {visible.length > 0 && (
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/70 px-2 py-3">
                <p className="text-xs text-muted-foreground">
                  第 {currentPage} / {pageCount} 页 · 本页 {pageRows.length} 条
                </p>
                <div className="flex items-center gap-2">
                  <NativeSelect
                    size="sm"
                    className="w-28"
                    value={String(pageSize)}
                    onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}
                  >
                    <NativeSelectOption value="12">每页 12 条</NativeSelectOption>
                    <NativeSelectOption value="25">每页 25 条</NativeSelectOption>
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

function formatChinaTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const formatted = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
  return `${formatted} 中国标准时间（UTC+8）`;
}
