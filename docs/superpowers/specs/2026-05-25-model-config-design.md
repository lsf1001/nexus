# 模型自定义配置设计方案

## 概述

支持用户自定义添加/编辑模型配置，通过本地配置文件 `~/.nexus/models.json` 存储，前端下拉菜单切换。

## 配置文件

路径：`~/.nexus/models.json`

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

## 后端接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/models` | GET | 获取模型列表 |
| `/api/models/switch` | POST | 切换当前模型 `{id: "model-id"}` |
| `/api/model` | GET | 获取当前模型信息 |

## 前端交互

- 侧边栏 Logo 下方添加模型下拉选择框
- 显示当前模型名称
- 点击展开显示所有模型列表
- 点击切换模型

## 流程

1. 后端启动 → 读取 `~/.nexus/models.json`
2. 前端加载 → 请求 `/api/models` 获取列表
3. 用户切换 → 请求 `/api/models/switch` → 后端重新初始化 Agent

## 文件修改

- `nexus/backend/config.py` - 加载模型配置文件
- `nexus/backend/main.py` - 添加模型管理接口
- `nexus/backend/agent.py` - 支持动态创建 Agent
- `frontend/src/components/Sidebar.tsx` - 添加模型选择下拉框
