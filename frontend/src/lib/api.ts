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
 * 读运行时注入的 WS token(来自 Vite/Nexus 启动期 env)。
 *
 * WHY 单独导出:WS 鉴权在 2026-07 改造为 Sec-WebSocket-Protocol 子协议,
 * token 不再进 URL。前端用此值填入 `new WebSocket(url, subprotocols)`
 * 第二个参数,或在 Tauri 模式下作为 `ws_open` invoke 独立参数传给 Rust relay。
 *
 * 失败行为:env 未注入时抛 Error,强制开发者/打包脚本显式配置。
 * 此前 `DEFAULT_TOKEN = 'nexus-default-token'` 兜底会让生产构建以
 * 公开字符串作为 token,任何反编译都能拿到 → 2026-07 删除默认值。
 */
export function getWsToken(): string {
  const token = import.meta.env.VITE_NEXUS_WS_TOKEN;
  if (typeof token === 'string' && token.length > 0) {
    return token;
  }
  throw new Error(
    'VITE_NEXUS_WS_TOKEN 未配置;WS 鉴权强制要求注入 token。' +
      '本地 dev:在 frontend/.env.local 写 VITE_NEXUS_WS_TOKEN=...; ' +
      'DMG:打包脚本会从后端 ws_token 自动注入,缺失说明后端 NEXUS_WS_TOKEN 未设。',
  );
}

/**
 * apiFetch 接受相对或绝对路径。
 * 路径会被 resolveApiUrl 补全,Tauri webview 自动用 http://127.0.0.1:30000。
 *
 * WHY 不抛错:后端 REST 鉴权依赖 ws_token;env 缺失时 Bearer header 留空,
 * 后端 401 返回给调用方由其决定重试 / 引导配置,前端不阻断渲染。
 */
export function apiFetch(
  input: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = import.meta.env.VITE_NEXUS_WS_TOKEN as string | undefined;
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(resolveApiUrl(input), { ...init, headers });
}

export interface MemoryInfo {
  exists: boolean;
  path: string;
  content: string;
  bytes: number;
  lines: number;
}

/** 读取用户级长期记忆文件(~/.nexus/AGENTS.md)。 */
export async function fetchMemory(): Promise<MemoryInfo> {
  const res = await apiFetch('/api/memory');
  if (!res.ok) {
    throw new Error(`读取记忆失败: ${res.status}`);
  }
  return (await res.json()) as MemoryInfo;
}

// ============ MCP 工具 ============

export interface McpServerInfo {
  name: string;
  source: string;
  enabled: boolean;
}

export interface McpToolInfo {
  name: string;
  description: string;
}

export interface McpToolsResponse {
  servers: McpServerInfo[];
  tools: McpToolInfo[];
  server_count: number;
  tool_count: number;
}

/** 列出已连接的 MCP 服务器与加载到的工具。 */
export async function fetchMcpTools(): Promise<McpToolsResponse> {
  const res = await apiFetch('/api/mcp/tools');
  if (!res.ok) {
    throw new Error(`读取 MCP 工具失败: ${res.status}`);
  }
  return (await res.json()) as McpToolsResponse;
}

// ============ 微信通道 ============

export interface WechatQrResponse {
  success?: boolean;
  qrcode_url?: string;
  qrcode?: string;
  session_key?: string;
  error?: string;
}

export interface WechatBindStatus {
  bound: boolean;
  account_id?: string;
  status?: string;
}

export interface ChannelInfo {
  id: string;
  type: string;
  status: string;
  enabled: boolean;
}

/** 获取微信登录二维码。 */
export async function fetchWechatQr(): Promise<WechatQrResponse> {
  const res = await apiFetch('/api/channels/wechat/qr', { method: 'POST' });
  return (await res.json()) as WechatQrResponse;
}

/** 轮询微信二维码扫描状态。 */
export async function fetchWechatQrStatus(
  sessionKey: string,
  timeoutMs = 10000,
): Promise<Record<string, unknown>> {
  const res = await apiFetch(
    `/api/channels/wechat/status/${encodeURIComponent(sessionKey)}?timeout_ms=${timeoutMs}`,
  );
  return (await res.json()) as Record<string, unknown>;
}

/** 获取微信绑定状态。 */
export async function fetchWechatBindStatus(): Promise<WechatBindStatus> {
  const res = await apiFetch('/api/channels/wechat/bind');
  return (await res.json()) as WechatBindStatus;
}

/** 绑定/恢复微信账号。 */
export async function postWechatBind(): Promise<Record<string, unknown>> {
  const res = await apiFetch('/api/channels/wechat/bind', { method: 'POST' });
  return (await res.json()) as Record<string, unknown>;
}

/** 解除微信绑定。 */
export async function deleteWechatBind(): Promise<Record<string, unknown>> {
  const res = await apiFetch('/api/channels/wechat/bind', { method: 'DELETE' });
  return (await res.json()) as Record<string, unknown>;
}

/** 获取所有通道状态。 */
export async function fetchChannels(): Promise<ChannelInfo[]> {
  const res = await apiFetch('/api/channels');
  const data = (await res.json()) as { channels?: ChannelInfo[] };
  return data.channels ?? [];
}

// ============ 模型切换 ============

/** 切换当前激活模型并同步 store。失败抛错由调用方处理。 */
export async function switchModel(id: string): Promise<void> {
  const res = await apiFetch('/api/models/switch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`切换模型失败: ${res.status} ${detail}`);
  }
}