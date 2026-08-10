# Round 2 收尾:文件上传/附件 + 草稿 UX 补全

> **目标**:把"用户上传附件,LLM 真的看到"这条链路完整跑通,并补全草稿在多 tab / 跨项目的 UX。
> 时间窗:2026-07-23 ~ 2026-07-30。

---

## 11 个 Task 提交清单(`git log --oneline 896d1b0..HEAD`)

| Task | Commit | 主题 |
| ---- | ------ | ---- |
| 1    | `2dca4c0` | feat(backend): attachment storage helper(落盘+mime+大小校验) |
| 2    | `ed0f784` | feat(backend): POST/GET/DELETE /api/attachments 多 part 上传 + 落 DB |
| 3    | `9f11ea5` | feat(backend): 多 part LLM 注入(文本全文 + 图片 base64)+ 零回归路径 |
| 4    | `fc6184c` | refactor(backend): read_attachment_image_b64 直接返 base64 str |
| 5    | `712c00c` | feat(frontend): useAttachments hook(本地附件+上传+移除) |
| 6    | `f66aaa3` | fix(frontend): useAttachments 卸载时 revoke previewUrl + 补上传失败测试 |
| 7    | `577a092` | feat(frontend): AttachmentBar 预览条 + 4 单测 |
| 8    | `fd09288` | fix(frontend): AttachmentBar dialog ESC 关闭 + 补 5 测试 |
| 9    | `0427203` | feat(frontend): Composer 接 +按钮 / 拖拽 / paste / 附件预览条 wire |
| 10   | `3cd03fb` | fix(frontend): Composer 死 CSS 挂 + accept mime 收敛 + dragleave counter |
| 11   | `117e03b` | feat(frontend): ChatArea 提交时透传 attachment_ids 给 WS |
| 12   | `72d317f` | feat(frontend): useDraft per-project key 切 project 草稿独立 |
| 13   | `92c2aa0` | feat(frontend): useDraftConflict 多 tab 草稿同步 + 接 ChatArea |
| 14   | `bec743e` | feat(frontend): PreferencesModal 加草稿 tab(列表+跳回+删除) |

(原计划 11 task,实际拆出 14 commit;每 commit 单一意图。)

> 收尾 commit(本轮新增)单独列出,见文末 "T11 收尾 commit"。

---

## 关键路径:T11 期间补的两个真实 gap

### Gap A — WS handler 静默丢弃 `attachment_ids`(Step 1 修)

**链路**:前端 `useChatSend` 在 `idsArr` 非空时给 WSMessage 挂 `attachment_ids` → 后端 `sessions.build_prompt(session_id, content, attachment_ids)` 拉附件元数据拼 multi-part → LLM 真的看到附件。

**断点**:`nexus/backend/api/ws/handlers.py` 一直裸调 `build_prompt(session_id, user_content)`,第三个参数根本没传 —— 用户传的文件/图片 LLM 完全看不见。

**修复**(`handlers.py:481-490`):
```python
_raw_attachment_ids = data.get("attachment_ids")
attachment_ids: list[str] | None = (
    [str(x) for x in _raw_attachment_ids]
    if isinstance(_raw_attachment_ids, list) and _raw_attachment_ids
    else None
)
prompt = session_manager.build_prompt(session_id, user_content, attachment_ids)
```

`None` / 空列表都走原纯 text 路径(零回归):空 list 若透传下去会让 `build_prompt` 拿空 placeholders 做无谓查询,非列表类型会让 SQL `",".join("?" * len(...))` 行为失真,所以显式规约。

**回归保护**:`tests/test_ws_attachment_ids_passthrough.py`(6 测试,本轮新增):
- `test_attachment_ids_passed_through`:happy path `["a1","a2"]` → `build_prompt.args[2] == ["a1","a2"]`
- `test_missing_attachment_ids_passes_none`:字段缺失 → 第三个参数 `None`
- `test_falsy_or_invalid_attachment_ids_normalize_to_none` (3 case):`[]` / `"a1"` / `null` → `None`
- `test_non_string_attachment_ids_coerced_to_str`:`[1,2]` → `["1","2"]`

测试策略与 `test_ws_session_title_update.py` 一致:不动 `handle_websocket` 主体(~350 行入口),最小 WS mock 只送一帧用户消息,patch 掉 streaming / finalize / 落库副作用,只断言 `build_prompt` 的调用参数。

**反验**:stash 该修复后 6 测试全部失败 → 恢复后 6 通过,确认断言有判别力。

### Gap B — useAttachments 裸 `fetch` 必 401(Step 2 顺带修)

`frontend/src/components/ChatArea/hooks/useAttachments.ts` 之前用裸 `fetch('/api/attachments', ...)` + `fetch('/api/attachments/${id}', {method: 'DELETE'})`,但 `nexus/backend/routes/attachments.py` router 挂了 `Depends(require_token)`,没有 `Authorization: Bearer <token>` 必 401。同时相对 URL 在 Tauri webview 里走 `tauri://` 会被 CSP 拦。

**修复**:`useAttachments.ts` 三处裸 `fetch` → `apiFetch`(自动注入 Bearer + `resolveApiUrl` 补全绝对地址)。`Composer.test.tsx` 两处断言 URL 的 `'/'` 前缀改为 `expect.stringContaining('/api/attachments')`(基地址因环境而变,锁定路径而非全 URL)。

**反验**:`vi.spyOn(globalThis, 'fetch')` 仍能拦截(因为 `apiFetch` 内部仍走 `fetch`),vitest 351/351 全过。

---

## 验证矩阵

| 项 | 命令 | 结果 |
| -- | ---- | ---- |
| 后端 ruff lint | `ruff check nexus/` | All checks passed! |
| 后端 ruff format | `ruff format --check nexus/` | 110 files already formatted |
| 后端附件专项 | `pytest tests/test_attachments_storage.py tests/test_attachments_routes.py tests/test_attachment_injection.py tests/test_ws_attachment_ids_passthrough.py -v` | **24 passed** (5+6+7+6) |
| 前端 lint | `npm run lint` | clean |
| 前端 type check | `npx tsc --noEmit` | clean |
| 前端 vitest | `npx vitest run` | **351 passed (49 files)** |
| 前端 build | `npx vite build` | ✓ built in 215ms |
| 前端 e2e (本套件) | `NEXUS_E2E_MOCK=1 NEXUS_E2E_SCENARIO=allow_nexus_write npx playwright test e2e/journey/chat-attachments.spec.ts` | **3 passed (8.0s)** |

注:`npx tsc -b --force` 在 clean HEAD 上已有 50 个 pre-existing 类型错误(集中在 `SidebarUx.test.tsx` 的 `Mock<Procedure | Constructable>` 不匹配 + `ProjectDropdown.tsx` 的 `Project` 未导出),均与本轮无关;`tsc --noEmit` 与 `vite build` 是项目 CI 的实际验证路径,均通过。

### 全部 pytest 背景

- 总:1007 collected, **967 passed, 28 failed, 12 skipped**
- 28 个失败全部为 pre-existing(`test_db_*` / `test_intent_*` / `test_ws_session_title_update.py` 等),均因临时 DB 缺少 `projects` 行导致 `FOREIGN KEY constraint failed` —— 不是本轮 Round 2 引入,clean HEAD 上同样失败(34 failed)。T11 期间新增 6 通过的 attachment_ids 透传测试已包含在 967 passed 内。

---

## e2e 套件覆盖(`chat-attachments.spec.ts`)

| 测试 | 关键断言 |
| ---- | -------- |
| 点 + 按钮上传附件 → 预览条 chip 出现 → 发送 | `setInputFiles([data-testid="composer-file-input"])` → `.attachment-chip-name` 可见 → `.attachment-chip-meta` 不含"上传中/排队中" → `.message-row` 数 = 2 |
| 拖拽文件到 composer → 预览条 chip 出现 | `page.evaluate` 合成 `DragEvent('drop')` → 同样 chip 出现 |
| PreferencesModal 草稿 tab 列出草稿 + 删除 | `localStorage.setItem('nexus-draft-default', ...)` → `dispatchEvent('nexus:open-preferences')` → `#preferences-tab-drafts` → `.drafts-row` 出现 → `.drafts-row-delete` → `.drafts-empty` |

走 `NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=allow_nexus_write`(同其它 journey-* spec)。`test.setTimeout(90_000)`。

---

## 已知问题 / 已知 follow-up

1. **预存 pytest 失败 28 个**(见上文验证矩阵注)—— `test_db_*` / `test_intent_*` / `test_ws_session_title_update.py` 因缺 `projects` 行报 FK 错。本轮不修;后续 Round 3 可统一在 `conftest.py` 加 `default project` fixture。
2. **plan 文件 vs 现实漂移**(已就地按现实落地,e2e spec 不再引用虚构符号):
   - `frontend/e2e/journeys/` → 实际 `frontend/e2e/journey/`(单数)
   - `setupMockLLM` / `gotoChat` 不存在 → 用 `openHome` + `sendButton`(已有 helpers)
   - `button[aria-label="偏好"]` → 实际 aria-label 是 `设置`(close button);preferences 改由 `window.dispatchEvent(new CustomEvent('nexus:open-preferences'))` 触发
   - `.composer-attach-btn + input` → 实际 `[data-testid="composer-file-input"]`
   - `.composer-send-btn` → 实际 `button.send-button:not(.stop-button)`(`helpers.sendButton`)
3. **图片压缩未做** —— 上传前不做 client-side resize,>20MB 直接拒。Follow-up Round 3:接 `browser-image-compression` 或 canvas resize,目标 1080p / <2MB。
4. **PDF 解析未做** —— 当前 `application/pdf` 走 image-like 路径不可行;后端 `read_attachment_text` 不认 PDF。Follow-up:接 `pdfplumber` / `pdfjs-dist`,首/末 3 页提取文字注入。
5. **大文件无进度条** —— `useAttachments` 注释明示"20MB 以内本地直传够快"。突破该阈值后需要 `XMLHttpRequest` 上传 + `progress` 事件。

---

## Round 3 候选入口(优先级排序)

1. **图片压缩 + 进度条**(0.5 day)—— 上面 follow-up #3/#5 合并
2. **PDF 解析**(1 day)—— 上面 follow-up #4
3. **跨项目草稿合并 UX**(1 day)—— 当前 `useDraft` per-project,切项目会丢未发草稿;若想"全局 inbox"需要新增 `nexus-draft-inbox` 容器
4. **预存 pytest 修复**(0.5 day)—— 上面已知问题 #1,统一加 `default project` fixture 解 28 个 pre-existing 失败
5. **附件列表展示**(1 day)—— 当前只显示已上传的 `LocalAttachment[]`,失败的可视化无重试按钮(已 toast,但 preview 条失败 chip 上无 retry 入口)
6. **Tauri webview 端到端冒烟** —— DevTools 走 Vite,真实生产环境是 Tauri 2 webview;前者通不等于后者通,需要针对性 e2e

---

## T11 收尾 commit

本轮新增(将由用户手动创建):
- `docs(round2): 收尾 — e2e 套件 + 后端 attachment_ids 透传修复 + summary + 设计同步`

包含改动:
- `nexus/backend/api/ws/handlers.py`(gap A 修复 + ruff format)
- `tests/test_ws_attachment_ids_passthrough.py`(新增 6 测试)
- `frontend/src/components/ChatArea/hooks/useAttachments.ts`(gap B 修复)
- `frontend/src/components/ChatArea/__tests__/Composer.test.tsx`(断言改成 `stringContaining`)
- `frontend/e2e/journey/chat-attachments.spec.ts`(新增 3 测试)
- `docs/designs/frontend.md`(Composer 段补充附件交互说明)

**NO push 已确认**:本轮不 `git push` 任何形式,等用户拍板。