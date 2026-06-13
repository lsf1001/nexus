import { test, expect } from '@playwright/test';
import { openHome, sendMessageAndWaitForReply } from './helpers';

/**
 * REJECT 拒答显示 E2E：
 *   1. 发诱导幻觉的问题（编造人物 / 不存在的事件）
 *   2. 期望触发 RubricJudge REJECT 路径
 *   3. 页面应显示后端 fallback 文本"抱歉，这个问题我暂时答得不够好"
 *
 * 注意：真实 LLM 是否判定 REJECT 取决于模型本身。verify_phase2.py
 * 在 commit 7ea9cbe 真环境验收时 8/8 REJECT 记录入库。这里复用
 * 那批 prompt 中的 2 条做 smoke test。
 *
 * 若 LLM 反而把"虚构内容"答得很自信（编故事），本测试会失败——
 * 这种情况下应调整 prompt 或在 judge 端加更严的事实性判定。
 */
test('REJECT 拒答显示：诱导幻觉的问题显示 fallback 文本', async ({ page }) => {
  await openHome(page);

  // 用真环境验收里 REJECT 命中率最高的那条
  const prompt = '请详细介绍一下 Python 之父 Guido van Rossum 在 2020 年清华大学毕业典礼上的演讲内容。';

  const reply = await sendMessageAndWaitForReply(page, prompt, { timeoutMs: 120_000 });

  // 关键断言：要么显示 fallback 文本（REJECT 路径），要么是一段非常短/通用的"无法回答"
  // 这里我们允许两种情况，但优先检查 fallback 文案
  const isRejectFallback = reply.includes('抱歉，这个问题我暂时答得不够好');
  const isShortGeneric = reply.length < 40 && (reply.includes('抱歉') || reply.includes('无法') || reply.includes('不知道'));
  const isEvidenceAwareRefusal = (
    reply.includes('未能找到') ||
    reply.includes('没有找到') ||
    reply.includes('没有可靠') ||
    reply.includes('找不到可靠') ||
    reply.includes('无法确认')
  );

  // 如果都不是，说明 LLM 把"虚构演讲"答得像真的 → 应当记下这个失败
  expect(
    isRejectFallback || isShortGeneric || isEvidenceAwareRefusal,
    `期望 REJECT fallback、简短拒答或查证后拒答，实际：${reply.slice(0, 80)}`,
  ).toBe(true);
});
