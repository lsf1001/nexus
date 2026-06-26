/**
 * HITL 确认卡片 E2E — mock LLM 模式。
 *
 * 配套 hitl-confirm.spec.ts:那个是真实 LLM 路径,LLM 行为不稳,本 spec
 * 是 mock LLM 路径,100% 决定性。
 *
 * 启动方式(后端 env):
 *   NEXUS_E2E_MOCK=1
 *   NEXUS_E2E_SCENARIO=interrupt_agents_md
 *
 * mock 行为:不管用户 prompt 是什么,首次 LLM 调用就返回 write_file
 * 工具调用写 ~/.nexus/AGENTS.md → 命中 FilesystemPermission interrupt
 * 规则 → 后端发 confirmation_request → 前端 .confirm-card 出现。
 *
 * 副作用:会覆盖真 ~/.nexus/AGENTS.md。spec 用 beforeAll / afterAll
 * 备份还原。
 *
 * 为什么单独写一个 spec:后端启动时按 NEXUS_E2E_SCENARIO 锁定场景,
 * 一个 spec 跑不动两个 scenario;但 CI 默认 scenario=allow_nexus_write
 * 是不触发 HITL 的无害路径,只有专门测 HITL 的 spec 才需要切到
 * interrupt_agents_md。
 */
import { test, expect } from '@playwright/test';
import { openHome, messageInput, sendButton } from './helpers';

test.skip(
  process.env.NEXUS_E2E_MOCK !== '1',
  '需要 NEXUS_E2E_MOCK=1 启用 mock LLM'
);
test.skip(
  process.env.NEXUS_E2E_SCENARIO !== 'interrupt_agents_md',
  '需要 NEXUS_E2E_SCENARIO=interrupt_agents_md 触发 HITL 路径'
);

test('HITL 确认卡片 (mock):触发 → 批准 → 流完成', async ({ page }) => {
  test.setTimeout(60_000);

  await openHome(page);

  // mock 收到 prompt 立刻返回 write_file(写 AGENTS.md)→ 命中 interrupt。
  // prompt 内容对 mock 无意义,只填一个能明确语义的话。
  const prompt = '请帮我整理一下长期记忆';
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

  // 注:不再断言 AGENTS.md 磁盘内容。deepagents write_file 走 StateBackend
  // (虚拟,非真磁盘),HITL 批准后 StateBackend 写,文件不进 ~/.nexus/AGENTS.md
  // 实盘。HITL 流程本身已通过"卡片 + 批准 + 流完成 + bug #58"验证。
  // AGENTS.md 落盘正确性是 deepagents 内部职责,不在 e2e 范围。
});
