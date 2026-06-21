const DEFAULT_TOKEN = 'nexus-default-token';

export function getRuntimeToken(): string {
  return import.meta.env.VITE_NEXUS_WS_TOKEN || DEFAULT_TOKEN;
}

export function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${getRuntimeToken()}`);
  return fetch(input, { ...init, headers });
}
