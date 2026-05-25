# Nexus 龙猫主题 UI 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Nexus 前端重构成龙猫主题 UI，采用森林绿+暖木色配色，添加真实龙猫 GIF mascot

**Architecture:** 基于 Tailwind CSS v4 的现代 React 前端，主题通过 CSS 变量和 Tailwind 扩展实现，龙猫元素作为视觉装饰嵌入侧边栏

**Tech Stack:** React 19 + TypeScript + Tailwind CSS v4 + Vite + Zustand

---

## 文件结构

```
frontend/src/
├── index.css              # 全局样式 + 龙猫主题 CSS 变量
├── components/
│   ├── Sidebar.tsx        # 侧边栏：森林绿 + 龙猫 GIF + Toggle
│   ├── ChatArea.tsx       # 主聊天区：温暖米色背景
│   └── ChatBubble.tsx     # 消息气泡：适配主题色
└── App.tsx                # 根组件
```

---

### Task 1: 更新 index.css 添加龙猫主题 CSS 变量

**Files:**
- Modify: `frontend/src/index.css:1-20`

- [ ] **Step 1: 添加龙猫主题 CSS 变量**

```css
@import "tailwindcss";

@theme {
  /* 龙猫森林绿配色 */
  --color-forest-start: #2D5A3D;
  --color-forest-end: #1E3D2A;
  --color-moss: #4A7C59;
  --color-moss-light: #A8C69F;
  --color-cream: #FAF6F0;
  --color-cream-dark: #F5EDE0;
  --color-wood: #E8D5B7;
  --color-text-dark: #4A3F2F;
  --color-text-muted: #7A6A5A;
  --color-border: #E8DCC8;
}
```

- [ ] **Step 2: 添加自定义样式**

在 `index.css` 末尾添加：

```css
/* 龙猫主题渐变背景 */
.forest-gradient {
  background: linear-gradient(180deg, var(--color-forest-start) 0%, var(--color-forest-end) 100%);
}

/* 龙猫 GIF 容器 */
.totoro-mascot {
  position: absolute;
  bottom: 60px;
  right: 15px;
  text-align: center;
}

.totoro-mascot img {
  width: 65px;
  height: 65px;
  object-fit: contain;
}

/* Toggle 开关样式 */
.toggle-switch {
  width: 40px;
  height: 22px;
  background: var(--color-moss);
  border-radius: 11px;
  position: relative;
  cursor: pointer;
  transition: background 0.2s;
}

.toggle-switch.off {
  background: #9CA3AF;
}

.toggle-switch::after {
  content: '';
  width: 18px;
  height: 18px;
  background: var(--color-wood);
  border-radius: 50%;
  position: absolute;
  right: 2px;
  top: 2px;
  transition: transform 0.2s;
}

.toggle-switch.off::after {
  transform: translateX(-20px);
}

/* 消息气泡圆角 */
.bubble-user {
  background: var(--color-wood) !important;
  color: var(--color-text-dark);
  border-radius: 16px 4px 16px 16px;
}

.bubble-assistant {
  background: var(--color-cream-dark) !important;
  color: var(--color-text-dark);
  border-radius: 4px 16px 16px 16px;
}

/* 思考过程样式 */
.thinking-block {
  margin-top: 8px;
  padding: 10px 14px;
  background: rgba(74, 124, 89, 0.08);
  border-left: 3px solid var(--color-moss);
  border-radius: 0 8px 8px 0;
  font-size: 12px;
  color: #5A6B52;
}
```

- [ ] **Step 3: 提交**

```bash
cd /Users/yxb/projects/nexus
git add frontend/src/index.css
git commit -m "feat: add totoro theme CSS variables and custom styles"
```

---

### Task 2: 重构 Sidebar.tsx 添加龙猫元素

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx`

- [ ] **Step 1: 编写新的 Sidebar 组件**

```tsx
import { useStore } from '../store/useStore';

function Sidebar() {
  const showThinking = useStore((s) => s.showThinking);
  const setShowThinking = useStore((s) => s.setShowThinking);

  return (
    <div className="w-64 forest-gradient flex flex-col relative">
      {/* Logo 区域 */}
      <div className="p-6">
        <h1 className="text-xl font-bold text-[var(--color-wood)] font-serif flex items-center gap-2">
          🌲 Nexus
        </h1>
      </div>

      {/* 中间区域 */}
      <div className="flex-1" />

      {/* 龙猫 Mascot */}
      <div className="totoro-mascot">
        <img
          src="https://media.giphy.com/media/26FPy3QZQqGtDcr6U/giphy.gif"
          alt="龙猫"
        />
        <div className="text-xs text-[var(--color-moss-light)] mt-1">森林精灵</div>
      </div>

      {/* Toggle 开关 */}
      <div className="p-4">
        <div className="bg-white/10 backdrop-blur-sm rounded-2xl p-4">
          <div className="text-xs text-[var(--color-moss-light)] mb-3">显示思考过程</div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowThinking(!showThinking)}
              className={`toggle-switch ${showThinking ? '' : 'off'}`}
              aria-label="切换显示思考"
            />
            <span className="text-xs text-[var(--color-wood)]">
              {showThinking ? 'ON' : 'OFF'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Sidebar;
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/Sidebar.tsx
git commit -m "feat: redesign Sidebar with totoro theme - forest green gradient, mascot GIF"
```

---

### Task 3: 重构 ChatBubble.tsx 适配龙猫配色

**Files:**
- Modify: `frontend/src/components/ChatBubble.tsx`

- [ ] **Step 1: 编写新的 ChatBubble 组件**

```tsx
import type { Message } from '../types';

interface ChatBubbleProps {
  message: Message;
  showThinking?: boolean;
}

function ChatBubble({ message, showThinking = true }: ChatBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-xl px-4 py-3 ${
          isUser ? 'bubble-user' : 'bubble-assistant'
        }`}
      >
        {message.content}
        {showThinking && message.thinking && (
          <div className="thinking-block">
            <div className="text-[10px] uppercase text-[var(--color-moss)] mb-2 flex items-center gap-1">
              🌿 思考过程
            </div>
            <pre className="whitespace-pre-wrap text-xs">{message.thinking}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

export default ChatBubble;
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/ChatBubble.tsx
git commit -m "feat: update ChatBubble with totoro theme colors and thinking style"
```

---

### Task 4: 重构 ChatArea.tsx 适配龙猫主题

**Files:**
- Modify: `frontend/src/components/ChatArea.tsx`

- [ ] **Step 1: 编写新的 ChatArea 组件**

```tsx
import { useState, useRef, useEffect } from 'react';
import { useStore } from '../store/useStore';
import ChatBubble from './ChatBubble';
import type { StreamEvent, WSMessage, Message } from '../types';

function ChatArea() {
  const wsRef = useRef<WebSocket | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const [displayMessages, setDisplayMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [showThinking, setShowThinking] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const isLoading = useStore((s) => s.isLoading);
  const wsConnected = useStore((s) => s.wsConnected);
  const setIsLoading = useStore((s) => s.setIsLoading);
  const setWsConnected = useStore((s) => s.setWsConnected);
  const setWsError = useStore((s) => s.setWsError);

  const wsUrl = import.meta.env.DEV
    ? 'ws://localhost:8000/api/ws'
    : 'ws://localhost:8000/api/ws';

  useEffect(() => {
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onerror = () => {
      setWsConnected(false);
      setWsError('连接错误');
    };

    ws.onopen = () => {
      setWsConnected(true);
    };

    ws.onclose = () => {
      setWsConnected(false);
    };

    ws.onmessage = (event) => {
      const data: StreamEvent = JSON.parse(event.data);

      switch (data.type) {
        case 'thinking': {
          if (messagesRef.current.length > 0) {
            const lastIdx = messagesRef.current.length - 1;
            messagesRef.current[lastIdx].thinking =
              (messagesRef.current[lastIdx].thinking || '') + data.content;
            setDisplayMessages([...messagesRef.current]);
          }
          break;
        }
        case 'chunk': {
          if (messagesRef.current.length > 0) {
            const lastIdx = messagesRef.current.length - 1;
            if (messagesRef.current[lastIdx].role === 'assistant') {
              messagesRef.current[lastIdx].content += data.content;
            }
            setDisplayMessages([...messagesRef.current]);
          }
          break;
        }
        case 'final': {
          if (messagesRef.current.length > 0) {
            const lastIdx = messagesRef.current.length - 1;
            messagesRef.current[lastIdx].content = data.content;
            setDisplayMessages([...messagesRef.current]);
          }
          setIsLoading(false);
          break;
        }
        case 'done': {
          setIsLoading(false);
          break;
        }
        case 'error': {
          setWsError(data.content);
          setIsLoading(false);
          break;
        }
        case 'token_usage': {
          break;
        }
      }
    };

    return () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [displayMessages, isLoading]);

  const handleSend = () => {
    const messageContent = input.trim();
    if (!messageContent || !wsConnected) return;

    setIsLoading(true);
    setInput('');

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: messageContent,
    };
    messagesRef.current.push(userMsg);
    setDisplayMessages([...messagesRef.current]);

    const assistantMsg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
    };
    messagesRef.current.push(assistantMsg);
    setDisplayMessages([...messagesRef.current]);

    const msg: WSMessage = { content: messageContent };
    wsRef.current?.send(JSON.stringify(msg));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex-1 flex flex-col bg-[var(--color-cream)]">
      {/* Header */}
      <div className="h-[50px] border-b border-[var(--color-border)] px-5 flex items-center justify-between">
        <span className="text-sm text-[var(--color-text-muted)]">MiniMax-M2.7</span>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-[var(--color-moss)] rounded-full" />
          <span className="text-xs text-[var(--color-moss)]">已连接</span>
        </div>
      </div>

      {/* 连接断开提示 */}
      {!wsConnected && (
        <div className="bg-red-50 border-b border-red-200 px-4 py-2 text-sm text-red-600">
          连接已断开，请刷新页面重新连接
        </div>
      )}

      {/* 消息区域 */}
      <div className="flex-1 overflow-y-auto p-5">
        {displayMessages.length === 0 && !isLoading ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-[var(--color-text-muted)]">
              <p className="text-lg">Nexus 智能助手</p>
              <p className="text-sm mt-2">输入消息开始对话</p>
            </div>
          </div>
        ) : (
          displayMessages.map((msg) => (
            <ChatBubble key={msg.id} message={msg} showThinking={showThinking} />
          ))
        )}
        {isLoading && (
          <div className="flex justify-start mb-4">
            <div className="bg-[var(--color-cream-dark)] px-4 py-3 rounded-lg">
              <div className="flex gap-1">
                <span
                  className="w-2 h-2 bg-[var(--color-moss)] rounded-full animate-bounce"
                  style={{ animationDelay: '0ms' }}
                />
                <span
                  className="w-2 h-2 bg-[var(--color-moss)] rounded-full animate-bounce"
                  style={{ animationDelay: '150ms' }}
                />
                <span
                  className="w-2 h-2 bg-[var(--color-moss)] rounded-full animate-bounce"
                  style={{ animationDelay: '300ms' }}
                />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className="p-4 border-t border-[var(--color-border)]">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={wsConnected ? '输入消息...' : '连接中...'}
            disabled={!wsConnected || isLoading}
            className="flex-1 px-4 py-3 border border-[var(--color-border)] rounded-3xl bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-moss)] disabled:bg-gray-100"
          />
          <button
            onClick={handleSend}
            disabled={!wsConnected || !input.trim() || isLoading}
            className="w-11 h-11 bg-[var(--color-moss)] text-white rounded-full hover:bg-[var(--color-forest-start)] disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center justify-center text-lg"
          >
            ➤
          </button>
        </div>
      </div>
    </div>
  );
}

export default ChatArea;
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/ChatArea.tsx
git commit -m "feat: update ChatArea with totoro theme - cream background, moss accent"
```

---

### Task 5: 验证和测试

- [ ] **Step 1: 启动开发服务器**

Run: `cd /Users/yxb/projects/nexus/frontend && npm run dev`

- [ ] **Step 2: 截图验证**

使用 Playwright 截图验证 UI 效果，保存到项目截图目录

---

## 验收标准

1. ✅ 侧边栏显示森林绿渐变背景 (#2D5A3D → #1E3D2A)
2. ✅ 侧边栏底部显示龙猫 GIF (65x65px)
3. ✅ 龙猫 GIF 下方显示 "森林精灵" 标签
4. ✅ Toggle 开关使用 iOS 风格，带 ON/OFF 文字
5. ✅ 主聊天区使用温暖米色背景 (#FAF6F0)
6. ✅ 用户消息使用龙猫肚皮色 (#E8D5B7)
7. ✅ AI 消息使用淡米色背景 (#F5EDE0)
8. ✅ 思考过程显示为带树叶图标的绿色样式
9. ✅ 整体视觉风格圆润柔和 (16px 圆角)