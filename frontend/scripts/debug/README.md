# Debug / Diagnostic 工具

非测试,开发者排错用。**不在 Playwright testDir 内**,不进 CI。

## 用法

```bash
cd frontend
npx playwright test scripts/debug/debug-agnes-message.spec.ts
npx playwright test scripts/debug/diag-ws-page.spec.ts
```

## 文件

- `debug-agnes-message.spec.ts` — 读 ~/.nexus/ 内某条消息,辅助诊断
  消息结构 / 数据库内容。
- `diag-ws-page.spec.ts` — 采集 WS 帧时序,console 打时间线,辅助诊断
  WS 协议问题。