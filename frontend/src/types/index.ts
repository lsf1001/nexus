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
  type: 'thinking' | 'chunk' | 'tool_call' | 'tool_result' | 'final' | 'done' | 'error' | 'token_usage' | 'wechat_message';
  content?: string;
  token_count?: number;
  context_usage?: number;
}

export interface WSMessage {
  content: string;
  session_id?: string;
  title?: string;  // 用于创建新会话时传递标题
}