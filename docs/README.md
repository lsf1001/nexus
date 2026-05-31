# Nexus 文档

## 快速开始

```bash
pip install nexus
nexus install
nexus start
```

访问 http://localhost:30000/app/

## API

### 健康检查

```
GET /health
```

### 会话管理

| 接口                   | 方法     | 说明   |
| -------------------- | ------ | ---- |
| `/api/sessions`      | GET    | 会话列表 |
| `/api/sessions`      | POST   | 创建会话 |
| `/api/sessions/{id}` | GET    | 会话详情 |
| `/api/sessions/{id}` | PUT    | 更新会话 |
| `/api/sessions/{id}` | DELETE | 删除会话 |

### 模型管理

| 接口                   | 方法   | 说明   |
| -------------------- | ---- | ---- |
| `/api/model`         | GET  | 当前模型 |
| `/api/models`        | GET  | 模型列表 |
| `/api/models/switch` | POST | 切换模型 |

### WebSocket

```
ws://localhost:30000/api/ws?token=<token>
```

发送：`{"content": "消息内容"}`
接收：`thinking`, `chunk`, `final`, `done`

## 部署

### macOS

```bash
nexus install   # 注册 launchd
nexus start      # 启动
```

### Linux

```bash
nexus install   # 注册 systemd
nexus start     # 启动
```

## 配置

环境变量：`MINIMAX_API_KEY`, `NEXUS_WS_TOKEN`, `NEXUS_PORT`

配置文件：`~/.nexus/workspace/config/config.json`

## CLI

```bash
nexus install    # 安装服务
nexus start       # 启动
nexus stop        # 停止
nexus restart     # 重启
nexus status      # 状态
nexus logs        # 日志
nexus uninstall   # 卸载
nexus doctor      # 诊断
```

## 更多信息

- [GitHub](https://github.com/your-org/nexus)
- [产品需求文档](./PRD.md)
- [开发规范](./CLAUDE.md)

---

*最后更新: 2026-06-01*