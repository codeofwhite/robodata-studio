import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'RoboData Studio · by IPPLab',
  description: 'Local-first robot data collection, quality review, and export control plane.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN" className="dark"><body>{children}</body></html>;
}
