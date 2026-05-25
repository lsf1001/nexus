export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  thinking?: string;
  createdAt: Date;
}

export interface StreamEvent {
  type: 'thinking' | 'chunk' | 'tool_call' | 'tool_result' | 'final' | 'done' | 'error' | 'token_usage';
  content?: string;
  token_count?: number;
  context_usage?: number;
}

export interface WSMessage {
  content: string;
}