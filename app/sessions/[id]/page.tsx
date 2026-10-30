import { SessionConsole } from '@/components/session-console';

export default async function SessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SessionConsole sessionId={id} />;
}
