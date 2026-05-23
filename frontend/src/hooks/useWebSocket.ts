import { useEffect, useRef, useCallback } from 'react';
import { useStore } from '../store/useStore';
import type { StreamEvent, WSMessage, Message } from '../types';

export function useWebSocket() {
  const wsInstanceRef = useRef<WebSocket | null>(null);
  const thinkingBufferRef = useRef<string>('');
  const currentMessageIdRef = useRef<string | null>(null);
  const hasConnectedRef = useRef(false);

  const {
    currentSessionId,
    addMessage,
    updateMessage,
    addSession,
    setWsConnected,
    setCurrentSession,
    setIsLoading,
    setWsError,
  } = useStore();

  const connect = useCallback(() => {
    if (hasConnectedRef.current) return;
    hasConnectedRef.current = true;

    if (wsInstanceRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const ws = new WebSocket('ws://localhost:8000/ws');
    wsInstanceRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
    };

    ws.onclose = () => {
      setWsConnected(false);
      setIsLoading(false);
      wsInstanceRef.current = null;
    };

    ws.onerror = () => {
      setWsConnected(false);
      setWsError('连接错误，请检查服务器');
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
          setWsError(data.content);
          setIsLoading(false);
          break;
        }
      }
    };
  }, [currentSessionId, addMessage, updateMessage, addSession, setWsConnected, setCurrentSession, setIsLoading, setWsError]);

  const send = useCallback((content: string) => {
    if (wsInstanceRef.current?.readyState === WebSocket.OPEN) {
      thinkingBufferRef.current = '';
      currentMessageIdRef.current = null;
      setIsLoading(true);

      const msg: WSMessage = {
        session_id: currentSessionId || undefined,
        content,
      };
      wsInstanceRef.current.send(JSON.stringify(msg));
    }
  }, [currentSessionId, setIsLoading]);

  const disconnect = useCallback(() => {
    hasConnectedRef.current = false;
    wsInstanceRef.current?.close();
    wsInstanceRef.current = null;
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { connect, send, disconnect };
}