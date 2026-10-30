import { EpisodeReview } from '@/components/episode-review';

export default async function EpisodePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EpisodeReview episodeId={Number(id)} />;
}
