export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  thinking?: string;
  createdAt: Date;
}

export interface Session {
  id: string;
  title: string;
  showThinking: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export interface ModelConfig {
  name: string;
  contextWindow: number;
  apiBase: string;
}

export interface StreamEvent {
  type: 'thinking' | 'tool_call' | 'tool_result' | 'final' | 'done' | 'error' | 'session_created';
  content: string;
  session_id: string;
}

export interface WSMessage {
  session_id?: string;
  content: string;
}