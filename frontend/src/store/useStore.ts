import { create } from 'zustand';
import type { Message, Session, ModelConfig } from '../types';

interface AppState {
  sessions: Session[];
  currentSessionId: string | null;
  messages: Record<string, Message[]>;
  currentModel: string;
  models: ModelConfig[];
  showThinking: boolean;
  wsConnected: boolean;
  contextUsage: number;

  setCurrentSession: (id: string) => void;
  addSession: (session: Session) => void;
  addMessage: (sessionId: string, message: Message) => void;
  updateMessage: (sessionId: string, messageId: string, updates: Partial<Message>) => void;
  setMessages: (sessionId: string, messages: Message[]) => void;
  setWsConnected: (connected: boolean) => void;
  setContextUsage: (usage: number) => void;
  setShowThinking: (show: boolean) => void;
  setCurrentModel: (model: string) => void;
}

export const useStore = create<AppState>((set) => ({
  sessions: [],
  currentSessionId: null,
  messages: {},
  currentModel: 'MiniMax-M2.7',
  models: [
    { name: 'MiniMax-M2.7', contextWindow: 200000, apiBase: 'https://api.minimaxi.com/v1' },
  ],
  showThinking: true,
  wsConnected: false,
  contextUsage: 0,

  setCurrentSession: (id) => set({ currentSessionId: id }),

  addSession: (session) => set((state) => ({
    sessions: [session, ...state.sessions],
    currentSessionId: session.id,
  })),

  addMessage: (sessionId, message) => set((state) => ({
    messages: {
      ...state.messages,
      [sessionId]: [...(state.messages[sessionId] || []), message],
    },
  })),

  updateMessage: (sessionId, messageId, updates) => set((state) => ({
    messages: {
      ...state.messages,
      [sessionId]: (state.messages[sessionId] || []).map((msg) =>
        msg.id === messageId ? { ...msg, ...updates } : msg
      ),
    },
  })),

  setMessages: (sessionId, messages) => set((state) => ({
    messages: { ...state.messages, [sessionId]: messages },
  })),

  setWsConnected: (connected) => set({ wsConnected: connected }),
  setContextUsage: (usage) => set({ contextUsage: usage }),
  setShowThinking: (show) => set({ showThinking: show }),
  setCurrentModel: (model) => set({ currentModel: model }),
}));