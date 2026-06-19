# DMG CDP 真实 GUI 回归测试

> **目的**:在已经装好 Nexus.app 的本机 macOS 上,启动带 `--remote-debugging-port=9229` 的 Electron,直接 attach 到 renderer 跑 CDP,模拟人手操作验证核心交互。

## 前置

1. 已经 `npm install` 安装 `ws` 依赖(在 `frontend/node_modules/ws`)。
2. 已经构建并安装新 DMG:
   ```bash
   cd /Users/yxb/projects/nexus/desktop
   npm run pack  # 产出 ../release/Nexus-1.0.0-arm64.dmg
   hdiutil attach ../release/Nexus-1.0.0-arm64.dmg
   cp -R "/Volumes/Nexus 1.0.0-arm64/Nexus.app" /Applications/
   hdiutil detach "/Volumes/Nexus 1.0.0-arm64"
   ```
3. 后端在 30000 端口可访问(由 `nexus start` 或 `nexus desktop` 启动)。

## 启动 DMG(带 DevTools 远程调试端口)

```bash
NEXUS_DEVTOOLS=1 open /Applications/Nexus.app
sleep 6
curl -s http://127.0.0.1:9229/json/list | grep -E '"url"' | head -3
```

应看到 `http://127.0.0.1:30000/app/` target,以及它的 `webSocketDebuggerUrl`。

## 跑回归

```bash
cd /Users/yxb/projects/nexus/frontend
node e2e/dmg-cdp/test-dmg-regression.mjs   # 5 项核心:title/返回按钮/深色
node e2e/dmg-cdp/test-dmg-e10.mjs           # 模型配置 modal
node e2e/dmg-cdp/test-dmg-e11.mjs           # 长 stream(25s+)
```

## 覆盖

- `test-dmg-regression.mjs`:
  - R1 sidebar 标题用首条用户消息(不是 "新会话" 占位)
  - R2 设置视图有"← 返回聊天"按钮 + 可见
  - R3 点返回回到聊天区
  - R4 微信视图有"← 返回聊天"按钮 + 可见
  - R5 微信返回也工作
- `test-dmg-e10.mjs`:
  - 模型配置 modal 弹出、显示"模型配置"标题
- `test-dmg-e11.mjs`:
  - 长题(transformer 500 字)完整流式输出,25s 内收到最终内容
  - thinking 帧先到、然后 chunk 累积

## 设计取舍

- **不走 puppeteer-core**:Puppeteer 的 `browserWSEndpoint` 需要浏览器级 ws,Electron 给的是 page-level,所以用 raw `ws` 模块 + `Runtime.evaluate` / `Page.captureScreenshot` 直接走 CDP。
- **不走 AppleScript 模拟键盘**:本机需要 Accessibility 权限,cliccick 也一样。用 CDP `Input.insertText` + `Input.dispatchKeyEvent` 走渲染进程 IPC,React 18 能正常看到 input/keydown 合成事件,等同人手敲键盘。
- **不用 React native setter 旁路**:之前测试用 `set value` 绕过 React state,导致 B5/B6 假阳性。新测试用真实 key event 路径,可靠。
