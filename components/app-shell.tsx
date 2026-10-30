'use client';

import { Activity, Boxes, Database, Download, LayoutDashboard, Radio, Settings2 } from 'lucide-react';
import { useStudioCapabilities } from '@/hooks/use-studio-capabilities';

const nav = [
  { id: 'cloth', label: '布料任务', href: '/cloth', icon: Boxes },
  { id: 'dashboard', label: 'Dashboard', href: '/', icon: LayoutDashboard },
  { id: 'sessions', label: '采集会话', href: '/sessions', icon: Radio },
  { id: 'generation', label: '数据生成', href: '/generation', icon: Boxes },
  { id: 'episodes', label: 'Episodes', href: '/episodes', icon: Database },
  { id: 'exports', label: '导出中心', href: '/exports', icon: Download },
  { id: 'assets', label: '资产与材料', href: '/assets', icon: Boxes },
] as const;

export function AppShell({ children, current }: { children: React.ReactNode; current: string }) {
  const { extensions, error } = useStudioCapabilities();
  const visibleNav = nav.filter((item) => {
    if (item.id === 'cloth') return extensions.includes('cloth');
    if (item.id === 'generation') return extensions.includes('generation');
    if (item.id === 'assets') return extensions.includes('assets');
    return true;
  });
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border/70 bg-background/88 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-[1680px] items-center justify-between px-4 lg:px-6">
          <a href="/" className="flex items-center gap-2.5" aria-label="RoboData Studio 首页">
            <span className="grid size-8 place-items-center rounded-lg border border-primary/35 bg-primary/10 text-primary"><Activity className="size-4" /></span>
            <span><strong className="block text-sm leading-4">RoboData Studio</strong><small className="font-mono text-[9px] uppercase tracking-[0.14em] text-muted-foreground">Collection control plane · by IPPLab</small></span>
          </a>
          <div className="flex items-center gap-2 text-xs text-muted-foreground"><span className="status-led status-led-ok" /> Local platform <span className="hidden font-mono sm:inline">127.0.0.1</span></div>
        </div>
      </header>
      <div className="mx-auto grid max-w-[1680px] lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="hidden min-h-[calc(100vh-56px)] border-r border-border/70 p-3 lg:flex lg:flex-col">
          <nav className="space-y-1" aria-label="主导航">
            {visibleNav.map((item) => { const Icon = item.icon; const active = current === item.id; return <a key={item.id} href={item.href} className={`nav-item ${active ? 'nav-item-active' : ''}`} aria-current={active ? 'page' : undefined}><Icon />{item.label}</a>; })}
          </nav>
          <div className="mt-auto space-y-1 border-t border-border/70 pt-3">
            <a className="nav-item" href="#"><Boxes />Adapters <span className="ml-auto font-mono text-[10px]">1</span></a>
            <a className="nav-item" href="#"><Settings2 />设置</a>
          </div>
        </aside>
        <main className="min-w-0 px-4 py-5 pb-20 md:px-6 md:py-7 lg:px-8">{error && <p role="alert" className="mb-4 text-sm text-destructive">功能列表加载失败：{error}</p>}{children}</main>
      </div>
      <nav style={{ gridTemplateColumns: `repeat(${visibleNav.length}, minmax(0, 1fr))` }} className="fixed inset-x-3 bottom-3 z-40 grid rounded-xl border border-border/80 bg-background/92 p-1 shadow-2xl backdrop-blur-xl lg:hidden" aria-label="移动端导航">
        {visibleNav.map((item) => { const Icon = item.icon; const active = current === item.id; return <a key={item.id} href={item.href} className={`flex min-h-12 flex-col items-center justify-center gap-1 rounded-lg text-[10px] ${active ? 'bg-primary/10 text-primary' : 'text-muted-foreground'}`}><Icon className="size-4" />{item.label}</a>; })}
      </nav>
    </div>
  );
}
