/**
 * ChatArea 共享常量。
 *
 * 拆出原因:818 行单文件不便维护,且字符串 / 错误码字典易遗漏更新。
 */

export const QUICK_PROMPTS: ReadonlyArray<{ title: string; prompt: string }> = [
  { title: '整理今天的待办', prompt: '请帮我整理今天的待办，提炼重点和下一步行动。' },
  { title: '总结微信里的消息', prompt: '请根据我最近的微信消息，帮我整理要点和待办。' },
  { title: '帮我写一封回复', prompt: '帮我起草一段专业又自然的回复。' },
  { title: '记住这个项目背景', prompt: '请记住这个项目的背景、目标和当前进度，下次对话时自动想起来。' },
];

export const ERROR_MESSAGES: Readonly<Record<string, string>> = {
  auth: 'API 密钥无效或已过期，请检查配置',
  rate_limit_exhausted: '请求过于频繁，已重试多次仍失败，请稍后再试',
  timeout_exhausted: '响应超时，请稍后再试或检查网络',
  context_length: '对话过长，请开启新会话',
  content_filter: '内容被安全策略拦截',
  bad_request: '请求格式有误',
  agent_unavailable: 'AI 服务暂未启动',
  invalid_resume_token: '续传凭证已失效',
  unknown: '未知错误',
};

export function formatErrorMessage(code: string, raw: string): string {
  return ERROR_MESSAGES[code] ?? raw ?? '未知错误';
}
