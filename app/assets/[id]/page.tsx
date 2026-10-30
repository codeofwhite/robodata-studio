import { AppShell } from '@/components/app-shell';
import { AssetDetail } from '@/components/asset-detail';

export default function AssetPage() {
  return <AppShell current="assets"><AssetDetail /></AppShell>;
}
