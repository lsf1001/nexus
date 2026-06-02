import { create } from 'zustand';
import type { Message, Model } from '../types';

interface AppState {
  isLoading: boolean;
  wsConnected: boolean;
  showThinking: boolean;
  modelName: string;
  models: Model[];
  currentModelId: string | null;
  darkMode: boolean;
  conversationMessages: Message[];

  setIsLoading: (loading: boolean) => void;
  setWsConnected: (connected: boolean) => void;
  setShowThinking: (show: boolean) => void;
  setModelName: (name: string) => void;
  setModels: (models: Model[]) => void;
  setCurrentModelId: (id: string | null) => void;
  setDarkMode: (dark: boolean) => void;
  setConversationMessages: (messages: Message[]) => void;
  clearConversationMessages: () => void;
}

export const useStore = create<AppState>((set) => ({
  isLoading: false,
  wsConnected: false,
  showThinking: true,
  modelName: 'MiniMax-M2.7',
  models: [],
  currentModelId: null,
  darkMode: false,
  conversationMessages: [],

  setIsLoading: (loading) => set({ isLoading: loading }),
  setWsConnected: (connected) => set({ wsConnected: connected }),
  setShowThinking: (show) => set({ showThinking: show }),
  setModelName: (name) => set({ modelName: name }),
  setModels: (models) => set({ models }),
  setCurrentModelId: (id) => set({ currentModelId: id }),
  setDarkMode: (dark) => set({ darkMode: dark }),
  setConversationMessages: (messages) => set({ conversationMessages: messages }),
  clearConversationMessages: () => set({ conversationMessages: [] }),
}));
