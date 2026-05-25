# Nexus - 智能助手

Nexus 是夜小白科技有限公司开发的 AI 助手，基于 DeepAgents 框架，支持网络搜索、文件读写、对话记忆等功能。

## 功能特性

- **智能对话** - 基于 MiniMax-M2.7 模型的中文对话
- **网络搜索** - 支持 Yandex 和 DuckDuckGo 搜索
- **文件管理** - 读写文件，默认保存到 `~/Documents/Nexus`
- **对话记忆** - 跨对话记住上下文
- **Markdown 渲染** - 支持加粗、列表等格式
- **思考过程** - 可开关的 AI 思考过程显示

## 技术栈

- **前端**: React + TypeScript + Tailwind CSS + Zustand
- **后端**: FastAPI + DeepAgents + LangGraph
- **模型**: MiniMax-M2.7
- **数据库**: SQLite

## 项目结构

```
nexus/
├── frontend/                 # React 前端
│   ├── src/
│   │   ├── components/     # 组件
│   │   ├── store/          # Zustand 状态管理
│   │   └── App.tsx         # 主应用
│   └── public/             # 静态资源
├── nexus/
│   └── backend/            # FastAPI 后端
│       ├── agent.py         # Agent 核心
│       ├── tools.py         # 工具函数
│       └── main.py          # WebSocket 服务
├── docker-compose.yml       # Docker 部署配置
└── README.md               # 本文档
```

## 快速开始

### 一键安装

```bash
curl -fsSL https://.../install.sh | bash
```

安装后运行：
```bash
nexus
```

### 环境要求

- Python 3.11+
- Node.js 18+ (前端开发需要)
- MiniMax API Key

### 配置环境变量

```bash
export MiniMax_API_KEY="your-api-key-here"
export MiniMax_API_BASE="https://api.minimaxi.com/v1"  # 可选，默认值
export MODEL_NAME="MiniMax-M2.7"                        # 可选，默认 MiniMax-M2.7
export MODEL_TEMPERATURE="0.7"                         # 可选，默认 0.7
```

### 本地开发

**后端：**

```bash
cd nexus
python -m venv .venv
source .venv/bin/activate  # 或 .venv\Scripts\activate (Windows)
pip install -r requirements.txt

# 设置环境变量
export MiniMax_API_KEY="your-api-key"
export MODEL_NAME="MiniMax-M2.7"        # 可选
export MODEL_TEMPERATURE="0.7"         # 可选

# 启动后端
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**前端：**

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down
```

访问 http://localhost:3000

## 使用说明

### 对话功能

在输入框中输入消息，按回车或点击发送按钮发送消息。

### 文件操作

- **保存文件**: `写一个文件，文件名是 xxx，内容是 yyy`
- **读取文件**: `读取 ~/Documents/Nexus/xxx.txt`
- **列出文件**: `列出 ~/Documents/Nexus 目录下的文件`

### 搜索功能

- **网络搜索**: `搜索今天有什么新闻`

### 思考过程

点击侧边栏的开关按钮，可以开启或关闭 AI 思考过程的显示。

### 模型切换

点击侧边栏顶部的模型下拉菜单，可以切换不同模型配置。

## 模型配置

模型配置存储在 `~/.nexus/models.json`：

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

添加新模型：直接编辑 `~/.nexus/models.json` 文件，添加新的模型配置。

## API 接口

| 接口              | 方法        | 说明           |
| --------------- | --------- | ------------ |
| `/api/`         | GET       | 健康检查         |
| `/api/models`   | GET       | 获取模型列表      |
| `/api/models/switch` | POST   | 切换当前模型      |
| `/api/ws`       | WebSocket | 对话 WebSocket |

### WebSocket 对话

```javascript
const ws = new WebSocket('ws://localhost:8000/api/ws');

// 发送消息
ws.send(JSON.stringify({ content: '你好' }));

// 接收消息类型
// - token_usage: Token 用量
// - thinking: 思考过程
// - chunk: 响应内容片段
// - final: 最终响应
// - done: 完成
// - error: 错误信息
```

## 开发指南

### 添加新工具

在 `nexus/backend/tools.py` 中添加：

```python
@langchain_tool
def my_tool(param: str) -> str:
    """工具描述"""
    # 实现逻辑
    return result
```

然后在 `TOOLS` 列表中注册。

### 修改系统提示词

编辑 `nexus/.nexus/AGENTS.md` 修改 AI 身份和系统提示词。

## 问题排查

### 前端无法连接后端

确认后端运行在 8000 端口：

```bash
curl http://localhost:8000/api/
```

### AI 不回答问题

检查 API Key 是否正确配置：

```bash
echo $MiniMax_API_KEY
```

### 文件操作失败

确认 `~/Documents/Nexus` 目录存在且有写入权限。

## 许可证

专有项目 - 夜小白科技有限公司
