const DEFAULT_TOKEN = 'nexus-default-token';

export function getRuntimeToken(): string {
  return import.meta.env.VITE_NEXUS_WS_TOKEN || DEFAULT_TOKEN;
}

/**
 * 解析 API base URL。
 *
 * 关键陷阱:Tauri 2 webview 里 `window.location.protocol === 'tauri:'`,
 * `window.location.host === 'localhost'`,如果直接拼接成
 * `tauri://localhost/api/models` 去做 fetch,WKWebView 不代理这个 scheme,
 * 会被 CSP 拦或者直接抛 "Failed to fetch"。
 *
 * 必须用绝对地址 `http://127.0.0.1:30000` 才能命中本机 sidecar。
 * 浏览器 dev 模式(Vite proxy)继续走当前 host。
 */
export function getApiBase(): string {
  if (typeof window === 'undefined') {
    return 'http://127.0.0.1:30000';
  }
  const isTauri = '__TAURI_INTERNALS__' in window;
  if (isTauri) {
    return 'http://127.0.0.1:30000';
  }
  // 浏览器 dev:Vite 在 30077,proxy /api → 30000
  return `${window.location.protocol}//${window.location.host}`;
}

/**
 * 把相对或绝对路径补成绝对 URL。
 * 已经 http(s) 开头的原样返回,避免重复拼接。
 */
export function resolveApiUrl(input: string): string {
  if (/^https?:\/\//i.test(input)) return input;
  if (input.startsWith('//')) {
    const proto =
      typeof window !== 'undefined' ? window.location.protocol : 'http:';
    return `${proto}${input}`;
  }
  const base = getApiBase();
  return input.startsWith('/') ? `${base}${input}` : `${base}/${input}`;
}

/**
 * apiFetch 接受相对或绝对路径。
 * 路径会被 resolveApiUrl 补全,Tauri webview 自动用 http://127.0.0.1:30000。
 */
export function apiFetch(
  input: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${getRuntimeToken()}`);
  return fetch(resolveApiUrl(input), { ...init, headers });
}