/**
 * 密钥 / 敏感字符串的脱敏与判别工具。
 *
 * 设计原则:
 * - 默认全部脱敏,**任何 API key、token、密码的 UI 显示都走 maskSecret**,
 *   不允许在模板里直接写 ``value.slice(-4)`` 这种"显示尾部"逻辑。
 * - ``secretTail(value)`` 故意返回空串 — 历史 SetupView 把 API key 尾部
 *   4 位拼到右键菜单里,看似"用户自己输入能看到",实际:
 *   1) 右键菜单不需要主动复制就出现,等同明文落盘到 ContextMenu 状态;
 *   2) 屏幕共享 / 截图 / 录屏时容易泄露。
 *   删除该用法后,即使保留接口也只返回长度统计,不返回字符。
 */

export interface SecretMaskOptions {
  /** 中间遮罩字符,默认 6 个圆点;若想更紧凑可传 '•••'。 */
  maskChar?: string;
  /** 总可见字符数(只看长度,不含 maskChar);默认 0(完全隐藏)。 */
  visibleLength?: number;
}

const DEFAULT_MASK = '••••••';

/**
 * 把任意敏感字符串脱敏成 UI 友好的占位。
 *
 * Examples:
 *   maskSecret('')                  // '(空)'
 *   maskSecret('sk-abc123def456')   // '••••••'
 *   maskSecret('sk-abc123def456', { visibleLength: 0 }) // '••••••'
 *
 * WHY 默认 visibleLength=0:防止"显示尾 4 位"反模式。
 * 调用方若确实需要展示部分(例如账号 ID),应该用字段专门函数而非
 * ``maskSecret(secret, { visibleLength: 4 })``,避免误用。
 */
export function maskSecret(value: string | null | undefined, options: SecretMaskOptions = {}): string {
  if (!value) return '(空)';
  const mask = options.maskChar ?? DEFAULT_MASK;
  return mask;
}

/**
 * 返回"多少字符"统计,不返回任何字符内容。
 * 替换历史 ``value.slice(-4)`` 模式 — UI 想给"已配置"反馈时,告诉用户
 * "已设置 (24 字符)" 比 "末尾 XXXX" 更不泄露。
 */
export function secretLength(value: string | null | undefined): number {
  return value ? value.length : 0;
}

/**
 * 已知敏感字段名白名单。
 * 在表格 / 列表渲染字段时,可以用此函数判断是否走 maskSecret,
 * 防止有人新增 secret 列时忘记脱敏。
 *
 * WHY 用白名单而非黑名单:新出现的 secret 字段(比如以后加 Slack token)
 * 默认不脱敏会很危险;反过来常见的 username / email / url 都不该被误脱敏,
 * 用白名单强制新 secret 字段显式登记。
 */
const SECRET_FIELD_NAMES: ReadonlySet<string> = new Set([
  'api_key',
  'apiKey',
  'apikey',
  'token',
  'ws_token',
  'access_token',
  'refresh_token',
  'password',
  'secret',
  'authorization',
]);

export function isSecretField(fieldName: string): boolean {
  return SECRET_FIELD_NAMES.has(fieldName);
}