/**
 * AI TrafficOS Typed API Client
 * 
 * Handles base URL resolution, bearer token injection, automated 401 token refresh,
 * structured error handling, and typed HTTP helpers.
 */

export const ACCESS_TOKEN_KEY = 'ai_trafficos_access';
export const REFRESH_TOKEN_KEY = 'ai_trafficos_refresh';
export const AUTH_CHANGED_EVENT = 'ai_trafficos_auth_changed';

export class ApiError extends Error {
  status: number;
  details?: unknown;

  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

export function getBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/+$/, '');
}

export function getStoredTokens(): { accessToken: string | null; refreshToken: string | null } {
  if (typeof window === 'undefined') {
    return { accessToken: null, refreshToken: null };
  }
  try {
    return {
      accessToken: localStorage.getItem(ACCESS_TOKEN_KEY),
      refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY),
    };
  } catch {
    return { accessToken: null, refreshToken: null };
  }
}

export function setStoredTokens(accessToken: string, refreshToken: string): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
    window.dispatchEvent(
      new CustomEvent(AUTH_CHANGED_EVENT, {
        detail: { accessToken, refreshToken },
      })
    );
  } catch (error) {
    console.error('Failed to store auth tokens:', error);
  }
}

export function clearStoredTokens(): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    window.dispatchEvent(
      new CustomEvent(AUTH_CHANGED_EVENT, {
        detail: { accessToken: null, refreshToken: null },
      })
    );
  } catch (error) {
    console.error('Failed to clear auth tokens:', error);
  }
}

function normalizePath(endpoint: string): string {
  const clean = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  if (clean.startsWith('/api/v1/')) {
    return clean;
  }
  if (clean === '/api/v1') {
    return clean;
  }
  return `/api/v1${clean}`;
}

// In-flight refresh promise to prevent stampede of concurrent 401s
let refreshPromise: Promise<string | null> | null = null;

async function executeSilentRefresh(): Promise<string | null> {
  const { refreshToken } = getStoredTokens();
  if (!refreshToken) {
    clearStoredTokens();
    return null;
  }

  const baseUrl = getBaseUrl();
  try {
    const response = await fetch(`${baseUrl}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
      clearStoredTokens();
      return null;
    }

    const data = await response.json();
    if (data && data.access_token && data.refresh_token) {
      setStoredTokens(data.access_token, data.refresh_token);
      return data.access_token as string;
    } else {
      clearStoredTokens();
      return null;
    }
  } catch (error) {
    console.error('Silent refresh failed:', error);
    clearStoredTokens();
    return null;
  }
}

function parseErrorMessage(status: number, data: unknown): string {
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    if (typeof obj.detail === 'string') {
      return obj.detail;
    }
    if (Array.isArray(obj.detail)) {
      const messages = obj.detail
        .map((item) => (typeof item === 'object' && item?.msg ? item.msg : String(item)))
        .join(', ');
      if (messages) return messages;
    }
    if (typeof obj.message === 'string') {
      return obj.message;
    }
  }
  return `Request failed with status ${status}`;
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
  skipAuth?: boolean;
  retryOn401?: boolean;
}

export async function request<T = unknown>(
  endpoint: string,
  options: RequestOptions = {}
): Promise<T> {
  const baseUrl = getBaseUrl();
  const normalizedEndpoint = normalizePath(endpoint);
  
  let url = `${baseUrl}${normalizedEndpoint}`;
  if (options.params) {
    const searchParams = new URLSearchParams();
    Object.entries(options.params).forEach(([key, val]) => {
      if (val !== undefined && val !== null) {
        searchParams.append(key, String(val));
      }
    });
    const queryString = searchParams.toString();
    if (queryString) {
      url += (url.includes('?') ? '&' : '?') + queryString;
    }
  }

  const { accessToken } = getStoredTokens();
  const headers = new Headers(options.headers || {});

  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }

  let body: BodyInit | null | undefined = undefined;
  if (options.body !== undefined) {
    if (
      typeof options.body === 'string' ||
      options.body instanceof FormData ||
      options.body instanceof Blob ||
      options.body instanceof URLSearchParams
    ) {
      body = options.body;
    } else {
      headers.set('Content-Type', 'application/json');
      body = JSON.stringify(options.body);
    }
  }

  if (!options.skipAuth && accessToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  }

  const fetchOptions: RequestInit = {
    ...options,
    headers,
    body,
  };

  let response: Response;
  try {
    response = await fetch(url, fetchOptions);
  } catch (error) {
    throw new ApiError(0, error instanceof Error ? error.message : 'Network connection error', error);
  }

  // Handle 401 Unauthorized with single silent refresh
  const isAuthEndpoint =
    normalizedEndpoint.includes('/auth/login') ||
    normalizedEndpoint.includes('/auth/refresh') ||
    normalizedEndpoint.includes('/auth/register');

  const canRetry = options.retryOn401 !== false && !isAuthEndpoint;

  if (response.status === 401 && canRetry) {
    if (!refreshPromise) {
      refreshPromise = executeSilentRefresh().finally(() => {
        refreshPromise = null;
      });
    }

    const newAccessToken = await refreshPromise;

    if (newAccessToken) {
      headers.set('Authorization', `Bearer ${newAccessToken}`);
      const retryResponse = await fetch(url, {
        ...fetchOptions,
        headers,
      });

      if (!retryResponse.ok) {
        let errData: unknown;
        try {
          errData = await retryResponse.json();
        } catch {
          errData = await retryResponse.text();
        }
        const message = parseErrorMessage(retryResponse.status, errData);
        throw new ApiError(retryResponse.status, message, errData);
      }

      if (retryResponse.status === 204) {
        return undefined as unknown as T;
      }
      return (await retryResponse.json()) as T;
    } else {
      // Refresh failed, clear auth and redirect to /login if in browser
      clearStoredTokens();
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
      throw new ApiError(401, 'Session expired. Please log in again.');
    }
  }

  if (!response.ok) {
    let errData: unknown;
    try {
      errData = await response.json();
    } catch {
      try {
        errData = await response.text();
      } catch {
        errData = null;
      }
    }
    const message = parseErrorMessage(response.status, errData);
    throw new ApiError(response.status, message, errData);
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return (await response.json()) as T;
}

export async function get<T>(
  endpoint: string,
  params?: Record<string, string | number | boolean | undefined | null>,
  options?: Omit<RequestOptions, 'params'>
): Promise<T> {
  return request<T>(endpoint, { ...options, method: 'GET', params });
}

export async function post<T>(
  endpoint: string,
  data?: unknown,
  options?: Omit<RequestOptions, 'body'>
): Promise<T> {
  return request<T>(endpoint, { ...options, method: 'POST', body: data });
}

export async function put<T>(
  endpoint: string,
  data?: unknown,
  options?: Omit<RequestOptions, 'body'>
): Promise<T> {
  return request<T>(endpoint, { ...options, method: 'PUT', body: data });
}

export async function patch<T>(
  endpoint: string,
  data?: unknown,
  options?: Omit<RequestOptions, 'body'>
): Promise<T> {
  return request<T>(endpoint, { ...options, method: 'PATCH', body: data });
}

export async function del<T>(
  endpoint: string,
  options?: RequestOptions
): Promise<T> {
  return request<T>(endpoint, { ...options, method: 'DELETE' });
}

export const api = {
  request,
  get,
  post,
  put,
  patch,
  delete: del,
};

export const apiClient = api;
