import { test, expect } from '@playwright/test';
import { openHome } from './helpers';

/**
 * REJECT 拒答显示 E2E：
 *   1. 发诱导幻觉的问题（编造人物 / 不存在的事件）
 *   2. 期望触发 RubricJudge REJECT 路径或 LLM safety 自拒答
 *   3. 页面应显示"拒答"风格文本（fallback 文案或 LLM 自拒答）
 *
 * 不稳定性说明：
 *  - 真实 LLM 不一定每次都触发 RubricJudge REJECT。verify_phase2.py
 *    在 commit 7ea9cbe 真环境验收时 REJECT 是 best-effort（"⚠️ 没走
 *    REJECT fallback——可能 LLM 答得'对'"），不算失败。
 *  - LLM 还可能调 web_search / yandex_search 反复查证（曾观察到 12+ 次），
 *    流式持续时间可达 60s+。这里 timeout 给 180s，避开 tool 风暴。
 *  - 因此断言只做"软"匹配：含明确拒答信号即视为通过。
 *
 * 拒答信号词：
 *  - 后端 REJECT fallback: "抱歉，这个问题我暂时答得不够好"
 *  - LLM 自拒答常见表达: 抱歉 / 无法 / 找不到 / 没有可靠 / 没有找到 /
 *    未能 / 不能 / 不清楚 / 虚构 / 捏造 / 不实
 */
test('REJECT 拒答显示：诱导幻觉的问题应显示拒答风格文本', async ({ page }) => {
  await openHome(page);

  // 用 verify_phase2.py HALLUCINATION_PROMPTS 第 2 条：虚构算法 "Zorgon"。
  // 第 1 条（Guido 清华演讲）实测会触发 LLM 调 web_search 反复外网查证，
  // 在沙箱/隔离网络下 DNS / 403 失败导致无限重试，180s 拿不到 done。
  // "Zorgon 算法" 是 LLM 训练语料完全没覆盖的虚构词，LLM 倾向直接拒答，
  // 不需要调外部工具——更稳定。
  const prompt = "请告诉我关于 'Zorgon 算法' 的原理和在分布式系统中的应用。";

  // 自行等待最后一条 assistant 出现非空文本，不依赖 sendMessageAndWaitForReply
  // 的 assistantCount==userCount 断言（tool 风暴可能让计数错位）。
  const userRowsBefore = await page.locator('.message-row.is-user').count();
  const assistantRowsBefore = await page.locator('.message-row.is-assistant').count();

  await expect(page.getByPlaceholder('告诉 Nexus 你想完成什么')).toBeEnabled({ timeout: 30_000 });
  await page.getByPlaceholder('告诉 Nexus 你想完成什么').fill(prompt);
  await page
    .locator('button')
    .filter({ has: page.locator('svg path[d^="M12 19"]') })
    .click();

  // 等 user 气泡出现
  await expect
    .poll(async () => await page.locator('.message-row.is-user').count(), { timeout: 5_000 })
    .toBe(userRowsBefore + 1);

  // 等新一条 assistant 行出现 + 文本非空
  await expect
    .poll(
      async () => {
        const rows = page.locator('.message-row.is-assistant p');
        const count = await rows.count();
        if (count < assistantRowsBefore + 1) return null;
        const text = (await rows.nth(count - 1).innerText().catch(() => '')).trim();
        return text.length > 0 ? text : null;
      },
      { timeout: 180_000, intervals: [1000, 2000, 3000] },
    )
    .not.toBeNull();

  // 取最后一个 assistant **整条气泡**的纯文本做断言
  // 注意：不是只取最后一个 <p>——LLM 多段回复里"我没有找到"可能在第一段，
  // 最后一段是"请告诉我你实际想了解的是哪个"，单独的 <p> 取不到拒答信号。
  const reply = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll<HTMLElement>('.message-row.is-assistant'));
    if (rows.length === 0) return '';
    return (rows[rows.length - 1]?.innerText ?? '').trim();
  });

  // 拒答信号词：覆盖后端 REJECT fallback + LLM 自拒答常见表达
  const refuseSignals = [
    '抱歉，这个问题我暂时答得不够好', // 后端 REJECT fallback
    '抱歉',
    '无法',
    '找不到',
    '没有找到',
    '没有相关',
    '没有记录',
    '没有可靠',
    '未能',
    '不能',
    '不清楚',
    '虚构',
    '捏造',
    '不实',
    '凭空',
    '没有公开',
    '无法确认',
    '未发现',
    '没有这场',
  ];
  const matched = refuseSignals.find((sig) => reply.includes(sig));

  // 软断言：只要有任一拒答信号就视为通过
  expect(
    matched,
    `期望回复含拒答信号（${refuseSignals.slice(0, 5).join(' / ')}...），实际前 120 字: ${reply.slice(0, 120)}`,
  ).toBeTruthy();
});
