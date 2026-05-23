import { useEffect, useRef, useCallback } from 'react';
import { useStore } from '../store/useStore';
import type { StreamEvent, WSMessage, Message } from '../types';

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const thinkingBufferRef = useRef<string>('');
  const currentMessageIdRef = useRef<string | null>(null);

  const {
    currentSessionId,
    addMessage,
    updateMessage,
    addSession,
    setWsConnected,
    setCurrentSession,
    setIsLoading,
  } = useStore();

  const connect = useCallback((sessionId?: string) => {
    const wsUrl = `ws://localhost:8000/ws${sessionId ? `?session_id=${sessionId}` : ''}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setWsConnected(true);
    };

    ws.onclose = () => {
      setWsConnected(false);
      setIsLoading(false);
    };

    ws.onerror = () => {
      setWsConnected(false);
      setIsLoading(false);
    };

    ws.onmessage = (event) => {
      const data: StreamEvent = JSON.parse(event.data);

      switch (data.type) {
        case 'session_created': {
          const newSession = {
            id: data.session_id,
            title: '新对话',
            showThinking: true,
            createdAt: new Date(),
            updatedAt: new Date(),
          };
          addSession(newSession);
          setCurrentSession(data.session_id);
          break;
        }

        case 'thinking': {
          if (currentSessionId) {
            thinkingBufferRef.current += data.content;
            if (currentMessageIdRef.current) {
              updateMessage(currentSessionId, currentMessageIdRef.current, {
                content: thinkingBufferRef.current,
              });
            } else {
              const msgId = crypto.randomUUID();
              currentMessageIdRef.current = msgId;
              const msg: Message = {
                id: msgId,
                role: 'assistant',
                content: data.content,
                createdAt: new Date(),
              };
              addMessage(currentSessionId, msg);
            }
          }
          break;
        }

        case 'tool_result': {
          if (currentSessionId && currentMessageIdRef.current) {
            updateMessage(currentSessionId, currentMessageIdRef.current, {
              content: thinkingBufferRef.current + '\n[工具返回] ' + data.content,
            });
          }
          break;
        }

        case 'final': {
          if (currentSessionId && currentMessageIdRef.current) {
            updateMessage(currentSessionId, currentMessageIdRef.current, {
              content: data.content,
              thinking: thinkingBufferRef.current,
            });
            thinkingBufferRef.current = '';
            currentMessageIdRef.current = null;
          }
          setIsLoading(false);
          break;
        }

        case 'done': {
          setIsLoading(false);
          break;
        }

        case 'error': {
          console.error('WebSocket error:', data.content);
          setIsLoading(false);
          break;
        }
      }
    };

    wsRef.current = ws;
  }, [currentSessionId, addMessage, updateMessage, addSession, setWsConnected, setCurrentSession, setIsLoading]);

  const send = useCallback((content: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      thinkingBufferRef.current = '';
      currentMessageIdRef.current = null;
      setIsLoading(true);

      const msg: WSMessage = {
        session_id: currentSessionId || undefined,
        content,
      };
      wsRef.current.send(JSON.stringify(msg));
    }
  }, [currentSessionId, setIsLoading]);

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