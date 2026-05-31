# Nexus - AI Gateway

Nexus 是夜小白科技有限公司开发的 AI Gateway，基于 DeepAgents 框架，支持会话管理、记忆系统、MCP 插件等功能。

## 功能特性

- **智能对话** - 基于 MiniMax-M2.7 模型的中文对话
- **会话管理** - 完整的会话 CRUD，支持软删除和恢复
- **记忆系统** - BM25 关键词检索，支持记忆保存和搜索
- **上下文窗口** - 85% 阈值自动压缩，Claude Code 风格
- **MCP 插件** - 支持 MCP 服务器扩展
- **WebSocket** - 实时流式响应
- **微信通道** - 集成微信消息处理
- **多模型支持** - MiniMax / DeepSeek / Qwen 等

## 技术栈

- **前端**: React + TypeScript + Tailwind CSS + Zustand
- **后端**: FastAPI + DeepAgents + SQLite
- **模型**: MiniMax-M2.7 / DeepSeek / Qwen
- **守护进程**: launchd (macOS) / systemd (Linux)

## 安装部署

### 方式一：一键安装脚本

```bash
curl -fsSL https://raw.githubusercontent.com/lsf1001/nexus/main/install.sh | bash
```

### 方式二：源码安装

```bash
# 克隆代码
git clone https://github.com/lsf1001/nexus.git ~/.nexus

# 创建虚拟环境
cd ~/.nexus
python3 -m venv .venv
source .venv/bin/activate  # 或 .venv\Scripts\activate (Windows)

# 安装依赖
pip install -e .

# 配置服务
nexus install

# 启动服务
nexus start
```

### 方式三：pip 安装（待 PyPI 发布）

```bash
pip install nexus
nexus install
nexus start
```

## CLI 命令

```bash
nexus install    # 注册服务（开机自启）
nexus start      # 启动服务
nexus stop       # 停止服务
nexus restart    # 重启服务
nexus status     # 查看运行状态
nexus logs       # 查看日志（-n 行数，-f 实时跟踪）
nexus uninstall  # 移除服务注册
nexus setup      # 交互式配置向导
nexus doctor     # 环境诊断
```

## 服务信息

| 项目 | 值 |
|------|-----|
| 进程名 | nexus-gateway |
| 端口 | 30000 |
| 前端地址 | http://localhost:30000/app/ |
| API 地址 | http://localhost:30000/api/ |
| 日志 | ~/.nexus/logs/ |
| 数据 | ~/.nexus/nexus.db |
| 守护 | launchd (macOS) / systemd (Linux) |

## 环境变量

```bash
export MiniMax_API_KEY="your-api-key"
export MiniMax_API_BASE="https://api.minimaxi.com/v1"  # 可选
export NEXUS_WS_TOKEN="nexus-default-token"           # WebSocket 认证
export NEXUS_PORT="30000"                              # 端口
```

## 项目结构

```
nexus/
├── frontend/                 # React 前端
│   ├── src/
│   │   ├── components/     # UI 组件
│   │   ├── store/           # Zustand 状态
│   │   ├── types/           # TypeScript 类型
│   │   ├── App.tsx           # 主应用
│   │   └── index.css         # 全局样式
│   └── public/              # 静态资源
├── nexus/
│   ├── backend/             # FastAPI 后端
│   │   ├── main.py          # 服务入口
│   │   ├── agent.py          # DeepAgents Agent
│   │   ├── sessions.py       # 会话管理
│   │   ├── memory.py        # 记忆系统
│   │   ├── db.py             # SQLite 数据库
│   │   └── channels/         # 通道实现
│   └── cli/                  # CLI 命令
│       ├── main.py           # CLI 入口
│       └── daemon/           # 守护进程
├── tests/                   # 测试
├── docs/                     # 文档
├── SPEC.md                   # 产品规格
├── CLAUDE.md                 # 开发规范
└── pyproject.toml            # Python 包配置
```

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/` | GET | API 信息 |
| `/api/sessions` | GET/POST | 会话列表/创建 |
| `/api/sessions/{id}` | GET/PUT/DELETE | 会话详情/更新/删除 |
| `/api/sessions/{id}/messages` | GET/POST | 消息列表/添加 |
| `/api/model` | GET | 当前模型信息 |
| `/api/models` | GET | 模型列表 |
| `/api/models/switch` | POST | 切换模型 |
| `/api/context` | GET | 上下文窗口信息 |
| `/api/context/compact` | POST | 触发压缩 |
| `/api/ws` | WebSocket | 实时对话 |

### WebSocket 对话

```javascript
const ws = new WebSocket('ws://localhost:30000/api/ws?token=nexus-default-token');

// 发送消息
ws.send(JSON.stringify({ content: '你好' }));

// 接收消息类型
// - thinking: 思考过程
// - chunk: 响应内容片段
// - final: 最终响应
// - done: 完成
// - error: 错误信息
```

## 模型配置

配置存储在 `~/.nexus/models.json`：

```json
{
  "models": [
    {
      "id": "default",
      "name": "MiniMax-M2.7",
      "api_key": "your-api-key",
      "api_base": "https://api.minimaxi.com/v1",
      "temperature": 0.7,
      "is_active": true
    }
  ]
}
```

## 开发

### 本地开发

```bash
# 克隆代码
git clone https://github.com/lsf1001/nexus.git
cd nexus

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -e .

# 启动后端
nexus gateway run

# 前端开发（另开终端）
cd frontend && npm install && npm run dev
```

### 测试

```bash
pytest tests/
```

## 问题排查

### 服务无法启动

```bash
# 检查状态
nexus status

# 查看日志
nexus logs

# 检查端口
lsof -i :30000
```

### 无法连接

```bash
# 检查服务
curl http://localhost:30000/health

# 环境诊断
nexus doctor
```

## 许可证

专有项目 - 夜小白科技有限公司