import { AppShell } from '@/components/app-shell';
import { GenerationCenter } from '@/components/generation-center';
import { ClothGenerationCenter } from '@/components/cloth-generation-center';
import { ClothforgeBatchPanel } from '@/components/clothforge-batch-panel';

export default function GenerationPage() {
  return <AppShell current="generation"><div className="space-y-6"><nav className="flex flex-wrap gap-5"><a href="#clothforge-batch" className="text-primary">ClothForge 批量运行</a><a href="#cube-generation" className="text-primary">方块轨迹生成</a><a href="#cloth-generation" className="text-primary">衣物外观生成</a></nav><ClothforgeBatchPanel /><details className="rounded-xl border p-4" id="cube-generation"><summary className="cursor-pointer font-medium">方块轨迹生成</summary><div className="mt-4"><GenerationCenter /></div></details><details className="rounded-xl border p-4" id="cloth-generation"><summary className="cursor-pointer font-medium">衣物外观生成</summary><div className="mt-4"><ClothGenerationCenter /></div></details></div></AppShell>;
}
