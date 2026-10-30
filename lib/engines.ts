export type EngineId = 'genesis' | 'isaac_sim' | 'roboverse';

export function engineLabel(engine: EngineId | string | null | undefined): string {
  if (engine === 'isaac_sim') return 'Isaac Sim';
  if (engine === 'genesis' || engine === 'clothtwin') return 'Genesis';
  if (engine === 'roboverse') return 'RoboVerse';
  return engine || 'Unknown';
}
