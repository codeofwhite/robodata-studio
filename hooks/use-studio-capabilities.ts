'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

export function useStudioCapabilities() {
  const [extensions, setExtensions] = useState<string[]>([]);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    void api<{ enabled_extensions: string[] }>('/health', { signal: controller.signal })
      .then((health) => {
        if (!Array.isArray(health.enabled_extensions)) {
          throw new Error('后端未提供功能列表，请使用配套版本');
        }
        setExtensions(health.enabled_extensions);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  return { extensions, error, loading };
}
