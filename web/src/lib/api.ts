export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export * from './api-client';

export async function getHealth(): Promise<{ status: string; [k: string]: unknown }> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5000);

  try {
    // Backend FastAPI route is /api/v1/health, with /health root alias
    let res = await fetch(`${API_BASE}/api/v1/health`, {
      signal: controller.signal,
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
      },
    });

    if (!res.ok && res.status === 404) {
      res = await fetch(`${API_BASE}/health`, {
        signal: controller.signal,
        cache: 'no-store',
        headers: {
          Accept: 'application/json',
        },
      });
    }

    if (!res.ok) {
      throw new Error(`Health check request failed with HTTP status ${res.status}`);
    }

    const data = await res.json();
    return data as { status: string; [k: string]: unknown };
  } finally {
    clearTimeout(timeoutId);
  }
}
