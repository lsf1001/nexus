import { useEffect, useRef, useCallback } from 'react';
import { useStore } from '../store/useStore';
import type { StreamEvent, WSMessage, Message } from '../types';

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const {
    currentSessionId,
    addMessage,
    addSession,
    setWsConnected,
    setCurrentSession,
  } = useStore();

  const connect = useCallback((sessionId?: string) => {
    const wsUrl = `ws://localhost:8000/ws${sessionId ? `?session_id=${sessionId}` : ''}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setWsConnected(true);
    };

    ws.onclose = () => {
      setWsConnected(false);
    };

    ws.onerror = () => {
      setWsConnected(false);
    };

    ws.onmessage = (event) => {
      const data: StreamEvent = JSON.parse(event.data);

      if (data.type === 'session_created') {
        const newSession = {
          id: data.session_id,
          title: '新对话',
          showThinking: true,
          createdAt: new Date(),
          updatedAt: new Date(),
        };
        addSession(newSession);
        setCurrentSession(data.session_id);
      } else if (data.type === 'thinking' || data.type === 'tool_result') {
        if (currentSessionId) {
          const msgId = crypto.randomUUID();
          const msg: Message = {
            id: msgId,
            role: 'assistant',
            content: data.content,
            createdAt: new Date(),
          };
          addMessage(currentSessionId, msg);
        }
      } else if (data.type === 'done') {
        // Done signal - can be used for any final cleanup
      }
    };

    wsRef.current = ws;
  }, [currentSessionId, addMessage, addSession, setWsConnected, setCurrentSession]);

  const send = useCallback((content: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const msg: WSMessage = {
        session_id: currentSessionId || undefined,
        content,
      };
      wsRef.current.send(JSON.stringify(msg));
    }
  }, [currentSessionId]);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  return { connect, send, disconnect };
}