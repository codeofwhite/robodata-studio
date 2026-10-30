import { AppShell } from '@/components/app-shell';
import { AssetLibrary } from '@/components/asset-library';

export default function AssetsPage() {
  return <AppShell current="assets"><AssetLibrary /></AppShell>;
}
