import { create } from 'zustand';
import type { Message } from '../types';

interface Model {
  id: string;
  name: string;
  api_key: string;
  api_base: string;
  temperature: number;
  is_active: boolean;
}

interface AppState {
  input: string;
  isLoading: boolean;
  wsConnected: boolean;
  showThinking: boolean;
  wsError: string | null;
  modelName: string;
  models: Model[];
  currentModelId: string | null;
  darkMode: boolean;
  conversationMessages: Message[];

  setInput: (input: string) => void;
  setIsLoading: (loading: boolean) => void;
  setWsConnected: (connected: boolean) => void;
  setShowThinking: (show: boolean) => void;
  setWsError: (error: string | null) => void;
  setModelName: (name: string) => void;
  setModels: (models: Model[]) => void;
  setCurrentModelId: (id: string | null) => void;
  setDarkMode: (dark: boolean) => void;
  setConversationMessages: (messages: Message[]) => void;
  clearConversationMessages: () => void;
}

export const useStore = create<AppState>((set) => ({
  input: '',
  isLoading: false,
  wsConnected: false,
  showThinking: true,
  wsError: null,
  modelName: 'MiniMax-M2.7',
  models: [],
  currentModelId: null,
  darkMode: false,
  conversationMessages: [],

  setInput: (input) => set({ input }),
  setIsLoading: (loading) => set({ isLoading: loading }),
  setWsConnected: (connected) => set({ wsConnected: connected }),
  setShowThinking: (show) => set({ showThinking: show }),
  setWsError: (error) => set({ wsError: error }),
  setModelName: (name) => set({ modelName: name }),
  setModels: (models) => set({ models }),
  setCurrentModelId: (id) => set({ currentModelId: id }),
  setDarkMode: (dark) => set({ darkMode: dark }),
  setConversationMessages: (messages) => set({ conversationMessages: messages }),
  clearConversationMessages: () => set({ conversationMessages: [] }),
}));
