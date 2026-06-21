# Nexus 前端

Nexus 个人 AI 助手的前端界面，技术栈为 React + TypeScript + Vite + Tailwind CSS + Zustand。

## 启动

```bash
# 安装依赖
npm install

# 开发模式 (默认 :30077)
npm run dev

# 类型检查 + 生产构建
npm run build

# 代码检查
npm run lint
```

> 开发服务默认监听 **30077**。可通过 `VITE_API_TARGET` 指定后端地址,默认 `http://localhost:30000`。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `VITE_API_TARGET` | `http://localhost:30000` | 后端 HTTP/WS 地址（开发期 Vite 代理目标） |

## 目录结构

```
frontend/
├── src/
│   ├── components/   # 视图组件
│   │   ├── ChatArea.tsx         # 主任务区 + 输入
│   │   ├── ChatBubble.tsx       # 单条消息渲染
│   │   ├── SessionList.tsx      # 侧边栏会话列表
│   │   ├── Sidebar.tsx          # 侧边栏壳
│   │   ├── ModelConfigModal.tsx # 模型配置弹窗
│   │   ├── WechatPluginModal.tsx# 微信通道二维码
│   │   └── ErrorBoundary.tsx    # 错误边界
│   ├── hooks/        # 自定义 Hook
│   ├── store/        # Zustand 全局状态
│   ├── types/        # TypeScript 类型定义
│   ├── assets/       # 静态资源
│   ├── App.tsx       # 根组件
│   └── main.tsx      # 入口
├── tests/
│   └── e2e/          # 端到端测试 (Playwright + Node WS)
└── vite.config.ts    # Vite 配置 (端口、代理)
```

## E2E 测试

```bash
# 后端 REST + WS 鉴权 (不依赖 LLM)
npm run e2e:backend

# 真实 LLM 流式响应（需后端配置 API 密钥）
npm run e2e:llm

# UI 全流程 (需前后端均启动)
npm run e2e

# 顺序跑全部
npm run e2e:all
```

测试产物 (截图、JSON 结果) 落在 `tests/e2e/artifacts/`,已 `.gitignore`,不会入库。

## WebSocket 协议

前端通过 `ws://<host>/api/ws?token=<NEXUS_WS_TOKEN>` 与后端建立长连接,事件顺序:

```
client send: { content, session_id? }
server send: session_created → thinking? → chunk* → final → done
```

- `session_created` 携带 `session_id`,前端用于后续同会话追问
- `chunk` 增量内容,累加应等于 `final.content`
- `thinking` 仅在模型支持思维链时出现
- 连接断开后会自动指数退避重连
