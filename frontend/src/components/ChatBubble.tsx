import { useEffect, useRef } from 'react';
import type { Message } from '../types';
import { useStore } from '../store/useStore';

interface ChatBubbleProps {
  message: Message;
}

export function ChatBubble({ message }: ChatBubbleProps) {
  const { showThinking } = useStore();
  const isUser = message.role === 'user';
  const contentRef = useRef(message.content);

  const displayedContent = message.content;

  useEffect(() => {
    contentRef.current = message.content;
  }, [message.content]);

  if (isUser) {
    return (
      <div className="flex justify-end mb-4">
        <div className="bg-blue-500 text-white px-4 py-2 rounded-lg max-w-md">
          {displayedContent}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start mb-4">
      <div className="bg-gray-100 px-4 py-2 rounded-lg max-w-md">
        <div className="text-gray-800 whitespace-pre-wrap">{displayedContent}</div>
        {message.thinking && showThinking && (
          <details className="mt-2">
            <summary className="text-xs text-gray-500 cursor-pointer">思考过程</summary>
            <div className="text-xs text-gray-400 mt-1 whitespace-pre-wrap">{message.thinking}</div>
          </details>
        )}
      </div>
    </div>
  );
}