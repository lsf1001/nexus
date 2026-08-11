/**
 * User Journey: HITL 拦截 deepagents 0.7.4 新增的 `delete` 工具
 *
 * 用户故事:
 *   1. 用户发任意 prompt → mock LLM 收到 → 调 `delete` 工具删 nexus/backend/x.py
 *   2. PathAwareHITLMiddleware 识别 `is_write_tool("delete") is True` →
 *      抛 GraphInterrupt → WS confirmation_request → `.confirm-card` 出现
 *   3. 弹窗显示工具名 = `delete` + 目标路径(0.7.4 字段集)
 *   4. 拒绝后 deepagents 把 ToolMessage(status=error) 回 LLM,LMM 反思不再删
 *   5. 验证目标文件未被删除(HITL 在工具执行前拦截)
 *
 * WHY 需要这个 spec:A.3 真 LLM E2E 验证 deepagents 0.7.4 新增的 `delete`
 * 工具被 PathAwareHITLMiddleware 识别为写工具并触发弹窗。
 *
 * 与 journey-hitl-workflow.spec.ts(测 write_file → HITL)是同构的,但工具名
 * 不同:write_file/edit_file 是 0.6.x 已有工具,delete 是 0.7.4 新增。
 * regression 必须显式验证 `delete` 字面工具名走的是同一拦截分支。
 *
 * Mock 模式(NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=delete_interrupt):
 *   - 后端用 mock LLM,首次 message 必返回 delete tool_call → nexus/backend/
 *     e2e_delete_target.py(非白名单 + 非 AGENTS.md)→ PathAwareHITL 触发
 *     GraphInterrupt → confirmation_request → .confirm-card
 *   - 不依赖真实 LLM 行为,CI 100% 稳跑
 *
 * 副作用:产生 nexus/backend/e2e_delete_target.py(beforeAll 创建, afterAll
 * 兜底删除 — 即使 spec 中途异常,文件也不会残留)
 *
 * 运行:
 *   NEXUS_E2E_MOCK=1 NEXUS_E2E_SCENARIO=delete_interrupt \
 *     npx playwright test e2e/journey/journey-delete-hitl.spec.ts
 */
import { test, expect } from '@playwright/test';
import { existsSync, writeFileSync, unlinkSync } from 'node:fs';
import { journeyOpenHome, hitlConfirmCard, hitlRejectButton } from './helpers';
import { messageInput, sendButton } from '../helpers';

const ARTIFACT_PATH = '/Users/yxb/projects/nexus/nexus/backend/e2e_delete_target.py';
const ARTIFACT_BODY = "# E2E delete target — created by journey-delete-hitl.spec.ts\n";

test.beforeAll(() => {
  // 先创建目标文件 — delete 工具有目标才能"删成功"。
  // 若缺失,deepagents FilesystemBackend 返回 "Error: 'xxx' not found",
  // 但 HITL 拦截在工具执行前,这个 fallback 路径不弹窗,spec 直接失败。
  writeFileSync(ARTIFACT_PATH, ARTIFACT_BODY);
});

test.afterAll(() => {
  // 拒绝分支下文件应保留;批准分支下文件会被删 — 都兜底删一次。
  if (existsSync(ARTIFACT_PATH)) unlinkSync(ARTIFACT_PATH);
});

// Mock 模式(NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=delete_interrupt)走 delete
// 工具 HITL 路径,默认 CI scenario=allow_nexus_write 不触发,本 spec 仅在
// delete_interrupt 场景跑。
//
// 2026-08-11 修:把 test.skip 放在 test() callback 顶层(此位置),CI 默认
// scenario 下 Playwright 标 skipped(=─)。原来 test.skip 在 callback 内部
// 条件 false 时 skip 会被 Playwright 报 ✘ (test.skip 失败语义),导致 CI
// 0ms fail × 3 retry(实际是 spec 设计,不是 bug)。
test.skip(
  process.env.NEXUS_E2E_MOCK !== '1' || process.env.NEXUS_E2E_SCENARIO !== 'delete_interrupt',
  '需要 NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=delete_interrupt;默认 CI scenario=allow_nexus_write 不跑',
);

test('HITL 拦截 deepagents 0.7.4 delete 工具', async ({ page }) => {
  test.setTimeout(120_000);

  await journeyOpenHome(page);

  // mock LLM 收到任意 message → 必返回 delete tool_call →
  // nexus/backend/e2e_delete_target.py(非白名单 + 非 AGENTS.md)→
  // PathAwareHITL 触发 GraphInterrupt → .confirm-card
  await expect(messageInput(page)).toBeEnabled({ timeout: 30_000 });
  await messageInput(page).fill('请删掉 nexus/backend/e2e_delete_target.py');
  await sendButton(page).click();

  await expect(page.locator('.message-row.is-user')).toHaveCount(1, { timeout: 10_000 });

  // 关键断言 1:HITL 弹窗必须出现
  // (若 is_write_tool("delete") 漏判 → FileSystemBackend 直接删文件,
  // .confirm-card 不出现,这条 assertion 60s 超时 fail)
  const card = hitlConfirmCard(page);
  await expect(card).toBeVisible({ timeout: 60_000 });

  // 关键断言 2:弹窗必须显示工具名 = "delete"(验证 PathAwareHITL 拦截分支
  // 真的走了"is_write_tool True → 弹窗"路径,而不是把 delete 当成未知工具
  // 默默放行)
  await expect(card.locator('.confirm-tool')).toContainText('delete');

  // 关键断言 3:弹窗必须显示目标路径(显示给用户审批的核心信息)
  await expect(card.locator('.confirm-target')).toContainText('e2e_delete_target.py');

  // 关键断言 4:文件在拒绝后必须保留(HITL 真的拦在工具执行前)
  await hitlRejectButton(page).click();
  await expect(card).toBeHidden({ timeout: 5_000 });
  expect(existsSync(ARTIFACT_PATH), 'reject 后文件应保留').toBe(true);
});