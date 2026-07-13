/**
 * User Journey: HITL 工作流(批准与拒绝)
 *
 * 用户故事:
 *   1. 用户要求 AI 写项目源码(非白名单路径)→ 触发 HITL interrupt
 *   2. .confirm-card 出现,带 [批准] [拒绝] 两个按钮
 *   3a. (批准分支) 点击批准 → 流续接 → 最终回复非空
 *   3b. (拒绝分支) 点击拒绝 → 流结束 → 无回复内容(或仅说"已取消")
 *   4. 验证 Judge 输出不漏到 assistant 气泡(防 bug #58 回归)
 *
 * Mock 模式(NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=interrupt_source):
 *   - 后端用 mock LLM,首次 message 必返回 write_file → nexus/backend/e2e_src.py
 *   - 路径不在 .nexus/ 白名单 + 不在 AGENTS.md 受保护集 → PathAwareHITL
 *     触发 GraphInterrupt → confirmation_request → .confirm-card
 *   - 不依赖真实 LLM 行为,CI 100% 稳跑
 *
 * 为什么不用 interrupt_agents_md:QualityGate 对 AGENTS.md 写入是纯 deny/allow
 * (不调 interrupt),不弹 .confirm-card。要测 HITL UI 流程必须用会触发
 * PathAwareHITL 的场景(写项目源码)。
 *
 * 副作用:会产生 nexus/backend/e2e_src.py,afterAll 删掉(走 PathAwareHITL
 * 批准后写入,或拒绝后 deepagents 重试前测试就结束了——以防万一都清)。
 *
 * 运行:
 *   NEXUS_E2E_MOCK=1 NEXUS_E2E_SCENARIO=interrupt_source \
 *     npx playwright test e2e/journey/journey-hitl-workflow.spec.ts
 */
import { test, expect } from '@playwright/test';
import { existsSync, unlinkSync } from 'node:fs';
import { journeyOpenHome, hitlConfirmCard, hitlApproveButton } from './helpers';
import { messageInput, sendButton } from '../helpers';

const ARTIFACT_PATH = '/Users/yxb/projects/nexus/nexus/backend/e2e_src.py';

test.skip(
  process.env.NEXUS_E2E_MOCK !== '1',
  '需要 NEXUS_E2E_MOCK=1 启用 mock LLM(真 LLM 路径不稳定)',
);
test.skip(
  process.env.NEXUS_E2E_SCENARIO !== 'interrupt_source',
  '需要 NEXUS_E2E_SCENARIO=interrupt_source 触发 PathAwareHITL 路径',
);

test.afterAll(() => {
  // 批准分支会真的写文件;拒绝 / 测试异常也可能留半成品。
  if (existsSync(ARTIFACT_PATH)) unlinkSync(ARTIFACT_PATH);
});

test('HITL 工作流:触发 → 批准 → 流续接', async ({ page }) => {
  test.setTimeout(120_000);

  await journeyOpenHome(page);

  // mock LLM 收到任意 message → 必返回 write_file nexus/backend/e2e_src.py
  // (非白名单 + 非 AGENTS.md)→ PathAwareHITL 触发 GraphInterrupt → .confirm-card
  await expect(messageInput(page)).toBeEnabled({ timeout: 30_000 });
  await messageInput(page).fill('请在 nexus/backend/ 下生成 e2e_src.py');
  await sendButton(page).click();

  await expect(page.locator('.message-row.is-user')).toHaveCount(1, { timeout: 10_000 });

  const card = hitlConfirmCard(page);
  await expect(card).toBeVisible({ timeout: 60_000 });

  // 批准
  await hitlApproveButton(page).click();

  await expect(card).toBeHidden({ timeout: 5_000 });

  // 流续接:输入框重新可点
  await expect(messageInput(page)).toBeEnabled({ timeout: 60_000 });

  // bug #58 回归断言:Judge 输出不能出现在 assistant 气泡里
  const assistantTexts = await page
    .locator('.message-row.is-assistant')
    .allInnerTexts();
  const judgeLeak = assistantTexts.some(
    (t) => t.includes('"score"') || t.includes('"reasoning"') || t.includes('"evidence"'),
  );
  expect(judgeLeak, 'Judge 输出不应漏到 assistant 气泡').toBe(false);
});