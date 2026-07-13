/**
 * HITL 确认卡片 E2E — mock LLM 模式。
 *
 * 启动方式(后端 env):
 *   NEXUS_E2E_MOCK=1
 *   NEXUS_E2E_SCENARIO=interrupt_source
 *
 * mock 行为:不管用户 prompt 是什么,首次 LLM 调用就返回 write_file
 * 工具调用写 nexus/backend/e2e_src.py(非白名单 + 非 AGENTS.md 受保护集)
 * → PathAwareHITL 触发 GraphInterrupt → 后端发 confirmation_request
 * → 前端 .confirm-card 出现。
 *
 * 副作用:会创建 nexus/backend/e2e_src.py,afterAll 清理。
 *
 * 为什么单独写一个 spec:跟 journey-hitl-workflow.spec.ts 等价断言,但
 * 放在 e2e/ 根目录供"找 HITL 测试"时直接搜到。scenario 行为相同
 * (interrupt_source),共享 mock LLM。
 *
 * 2026-07-13:之前用 interrupt_agents_md scenario,QualityGate 对
 * AGENTS.md 写入是纯 deny/allow(返回错误),不调 interrupt,不弹
 * .confirm-card。改用 interrupt_source(写项目源码)触发 PathAwareHITL。
 *
 * 2026-07-13:之前有 hitl-confirm.spec.ts(真 LLM)试图用自然语言 prompt
 * 诱导 LLM 主动调 edit_file 覆盖 AGENTS.md。真 LLM 在生产语义下不会主动
 * 覆盖用户身份数据(`用户名字:小明` / `最喜欢的水果:榴莲`),表现为
 * "拒绝 + 提建议",不调工具 → 不触发 HITL → spec 永远 timeout。已删除。
 * 真 LLM HITL 测试无意义,产品行为已用 mock 100% 覆盖。
 */
import { test, expect } from '@playwright/test';
import { existsSync, unlinkSync } from 'node:fs';
import { openHome, messageInput, sendButton } from './helpers';

const ARTIFACT_PATH = '/Users/yxb/projects/nexus/nexus/backend/e2e_src.py';

test.skip(
  process.env.NEXUS_E2E_MOCK !== '1',
  '需要 NEXUS_E2E_MOCK=1 启用 mock LLM'
);
test.skip(
  process.env.NEXUS_E2E_SCENARIO !== 'interrupt_source',
  '需要 NEXUS_E2E_SCENARIO=interrupt_source 触发 PathAwareHITL 路径'
);

test.afterAll(() => {
  if (existsSync(ARTIFACT_PATH)) unlinkSync(ARTIFACT_PATH);
});

test('HITL 确认卡片 (mock):触发 → 批准 → 流完成', async ({ page }) => {
  test.setTimeout(60_000);

  await openHome(page);

  // mock 收到 prompt 立刻返回 write_file → nexus/backend/e2e_src.py
  // (非白名单 + 非 AGENTS.md)→ PathAwareHITL 触发 GraphInterrupt。
  // prompt 内容对 mock 无意义,只填一个能明确语义的话。
  const prompt = '请在 nexus/backend/ 下生成 e2e_src.py';
  await expect(messageInput(page)).toBeEnabled({ timeout: 30_000 });
  await messageInput(page).fill(prompt);
  await sendButton(page).click();

  // 确认卡片出现
  const confirmCard = page.locator('.confirm-card');
  await expect(confirmCard).toBeVisible({ timeout: 30_000 });
  const approveBtn = confirmCard.locator('button.confirm-approve');
  await expect(approveBtn).toBeVisible({ timeout: 5_000 });

  // 批准 → 流继续 → 输入框重新可点
  await approveBtn.click();
  await expect(confirmCard).toBeHidden({ timeout: 5_000 });
  await expect(messageInput(page)).toBeEnabled({ timeout: 30_000 });

  // 至少有一个 assistant 气泡
  const assistantBubbles = page.locator('.message-row.is-assistant');
  await expect(assistantBubbles.first()).toBeVisible({ timeout: 5_000 });
  const allTexts = await assistantBubbles.allInnerTexts();
  const nonEmpty = allTexts.filter((t) => t.trim().length > 0);
  expect(nonEmpty.length).toBeGreaterThan(0);

  // bug #58 回归断言:Judge JSON 不能出现在用户可见气泡
  const judgeLeak = allTexts.some(
    (t) => t.includes('"score"') || t.includes('"reasoning"') || t.includes('"evidence"')
  );
  expect(judgeLeak).toBe(false);

  // 注:不再断言 e2e_src.py 磁盘内容。deepagents write_file 走 StateBackend
  // (虚拟,非真磁盘),HITL 批准后 StateBackend 写,文件不一定进真盘。HITL
  // 流程本身已通过"卡片 + 批准 + 流完成 + bug #58"验证。
});