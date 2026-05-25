import { create } from 'zustand';

interface AppState {
  input: string;
  isLoading: boolean;
  wsConnected: boolean;
  showThinking: boolean;
  wsError: string | null;
  modelName: string;

  setInput: (input: string) => void;
  setIsLoading: (loading: boolean) => void;
  setWsConnected: (connected: boolean) => void;
  setShowThinking: (show: boolean) => void;
  setWsError: (error: string | null) => void;
  setModelName: (name: string) => void;
}

export const useStore = create<AppState>((set) => ({
  input: '',
  isLoading: false,
  wsConnected: false,
  showThinking: true,
  wsError: null,
  modelName: 'MiniMax-M2.7',

  setInput: (input) => set({ input }),
  setIsLoading: (loading) => set({ isLoading: loading }),
  setWsConnected: (connected) => set({ wsConnected: connected }),
  setShowThinking: (show) => set({ showThinking: show }),
  setWsError: (error) => set({ wsError: error }),
  setModelName: (name) => set({ modelName: name }),
}));
