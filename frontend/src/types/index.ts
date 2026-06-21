export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  thinking?: string;
  createdAt: Date;
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
  updatedAt: string;
  channel?: string;
}

export interface SessionResponse {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  channel?: string;
}

export interface StreamEvent {
  type: 'thinking' | 'chunk' | 'tool_call' | 'tool_result' | 'final' | 'done' | 'error' | 'token_usage' | 'wechat_message' | 'session_created' | 'resume_token' | 'resume_ack' | 'invalid_resume_token' | 'stats' | 'clarification_request';
  content?: string;
  token_count?: number;
  context_usage?: number;
  session_id?: string;
  title?: string;
  // Phase 1 新增字段
  event_id?: number;       // 事件 ID（断点续传定位）
  error_code?: string;     // 错误代码（auth / rate_limit_exhausted / ...）
  retryable?: boolean;     // 是否可重试
  resume_token?: string;   // resume token（用于断线重连）
  last_event_id?: number;  // 当前流的最后 event_id
  // Task 1.10 可观测元事件 (type='stats')
  retries?: number;        // StreamGuard 重试次数
  fallbacks?: number;      // ResilientRunnable 降级次数
  events_emitted?: number; // StreamGuard 已发出事件总数
  // 澄清请求(type='clarification_request')
  options?: string[];      // 候选项 0-6 个;空时让用户自由输入
}

export interface WSMessage {
  content: string;
  session_id?: string;
  title?: string;  // 用于创建新会话时传递标题
}

export interface Model {
  id: string;
  name: string;
  api_key: string;
  api_base: string;
  temperature: number;
  is_active: boolean;
}