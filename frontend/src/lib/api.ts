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

// ============ Projects ============

export interface Project {
  id: string;
  name: string;
  display_name: string;
  path: string;
  description?: string;
  created_at?: string;
  updated_at?: string;
}

export interface CreateProjectInput {
  name: string;
  display_name: string;
  description?: string;
}

/** 列出所有项目。 */
export async function fetchProjects(): Promise<Project[]> {
  const res = await apiFetch('/api/projects');
  if (!res.ok) throw new Error(`读取 Projects 失败: ${res.status}`);
  return (await res.json()) as Project[];
}

/** 创建一个新项目,返回后端持久化的对象(含 path)。 */
export async function createProject(input: CreateProjectInput): Promise<Project> {
  const res = await apiFetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`创建 Project 失败: ${res.status} ${detail}`);
  }
  return (await res.json()) as Project;
}

/** 把指定项目置为全局 active,后端落盘到 ~/.nexus/active_project.json。 */
export async function activateProject(id: string): Promise<void> {
  const res = await apiFetch(`/api/projects/${encodeURIComponent(id)}/activate`, {
    method: 'POST',
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`切换 Project 失败: ${res.status} ${detail}`);
  }
}

/** 单条 skill 记录。source 由后端 skills_loader 给出:`"local"`(本地目录)或 `"project"`(链接到项目)。 */
export interface SkillItem {
  name: string;
  path: string;
  source: 'local' | 'project';
}

/** `GET /api/skills` 返回的包装 — 与 MCP 的 `McpToolsResponse` 对齐结构。 */
export interface SkillsResponse {
  project_id: string;
  skills: SkillItem[];
}

/** 读取某项目下可用的 skills 列表。后端返的是 `{project_id, skills[]}` 包装对象,不要直接当成数组用。 */
export async function fetchSkills(projectId: string): Promise<SkillsResponse> {
  const res = await apiFetch(`/api/skills?project_id=${encodeURIComponent(projectId)}`);
  if (!res.ok) throw new Error(`读取 skills 失败: ${res.status}`);
  return (await res.json()) as SkillsResponse;
}

/** 读取某项目作用域下的 MCP 工具(与无参 fetchMcpTools 不同 — 后者走全局默认)。 */
export async function fetchMcpToolsForProject(projectId: string): Promise<McpToolsResponse> {
  const res = await apiFetch(`/api/mcp/tools?project_id=${encodeURIComponent(projectId)}`);
  if (!res.ok) throw new Error(`读取 MCP 工具失败: ${res.status}`);
  return (await res.json()) as McpToolsResponse;
}

// ============ Plugins(Round 5 Task 5.2)============

/** 单条 plugin manifest — 与后端 `nexus/backend/plugins_scanner.py` 字段对齐。 */
export interface PluginManifest {
  name: string;
  version: string;
  description: string;
  type: string;
  path: string;
}

/** `GET /api/plugins` 返回的包装对象。 */
export interface PluginsResponse {
  plugins: PluginManifest[];
}

/** 列出 ~/.nexus/plugins/ 下扫描到的 manifest。本轮只读,无安装/卸载入口。 */
export async function fetchPlugins(): Promise<PluginsResponse> {
  const res = await apiFetch('/api/plugins');
  if (!res.ok) throw new Error(`读取 plugins 失败: ${res.status}`);
  return (await res.json()) as PluginsResponse;
}

// ============ 消息全文搜索(Round 3 Task 3.4)============

export interface SearchResult {
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  /** SQLite FTS5 snippet() 生成,含 <mark>...</mark> 高亮,前端 dangerouslySetInnerHTML 渲染 */
  snippet: string;
  created_at: string;
}

export interface SearchMessagesResponse {
  results: SearchResult[];
  count: number;
}

/**
 * 全局搜索消息正文 — GET /api/search/messages?q=...&limit=50。
 *
 * 后端走 SQLite FTS5(nexus/backend/search.py),snippet 字段已经含 <mark> 高亮,
 * 前端用 dangerouslySetInnerHTML 渲染。注意 content 是完整文本,snippet 是
 * 摘要(高亮 + 上下文),UI 上展示 snippet 就够,content 留给将来"点开看全
 * 文"扩展。
 */
export async function searchMessages(q: string, limit = 50): Promise<SearchMessagesResponse> {
  const qs = new URLSearchParams({ q, limit: String(limit) });
  const res = await apiFetch(`/api/search/messages?${qs.toString()}`);
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`搜索失败: ${res.status} ${detail}`);
  }
  return (await res.json()) as SearchMessagesResponse;
}

// ============ 通用 PATCH(Round 6.1 Task 8)============

/**
 * 通用 PATCH helper — Content-Type: application/json,返回解析后的 JSON。
 *
 * WHY 单独 helper:`apiFetch` 是底层 fetch wrapper(返 Response 不解析),
 * 上层 80% GET/POST/DELETE 场景都直接 fetch。只有 PATCH 当前只有 PATCH
 * /api/sessions/{id} style 这一处,但 Round 后续字段(title? show_thinking?)
 * 仍会走此 helper,避免每处都重复 method/headers/body/JSON/throw 模板。
 *
 * 错误处理:非 2xx 抛 ``Error(`${status}: ${detail}`)``,detail 优先取
 * ``response.json().detail``,fallback 到 statusText。422(Pydantic Literal
 * 校验失败)/ 400(非法 style)/ 404(session 不存在)都走这条路径。
 */
export async function apiPatch<T = unknown>(
  path: string,
  body: unknown,
): Promise<T> {
  const res = await apiFetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = (await res.json()) as { detail?: string };
      if (data?.detail) detail = data.detail;
    } catch {
      /* body 非 JSON,保留 statusText */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}