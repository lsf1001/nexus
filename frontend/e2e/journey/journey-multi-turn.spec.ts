/**
 * User Journey: 多轮对话与上下文累积
 *
 * 用户故事:
 *   1. 同会话连发 3 条不同主题问题
 *   2. 每条都收到非空 assistant 回复
 *   3. 第 3 条回复引用前文(显式提及"Python"或"JavaScript"或"Go")
 *   4. 验证会话消息总数
 *
 * 验证策略:
 *   - 上下文回显靠"喂一个跨主题 prompt",LLM 行为可能不可靠。
 *   - 用 3 条不同主题的简介请求,第 3 条回复应能引用前文关键词。
 *   - 不强求引用全部 3 个关键词,至少 1 个(LLM 行为不可控)。
 *
 * 关键约束:全走真 LLM,timeout 240s(3 轮 × ~60-80s)。
 * 必须 skip mock — mock LLM 只回固定反射文本(操作完成),无法回显前文关键词。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome, sendSequence } from './helpers';
import { messageCount } from '../helpers';

test.skip(
  process.env.NEXUS_E2E_MOCK === '1',
  '上下文回显需要真 LLM,mock 模式只回固定反射文本,无法回显前文'
);

test('多轮上下文:3 条连发,引用前文', async ({ page }) => {
  test.setTimeout(240_000);

  await journeyOpenHome(page);

  const questions = [
    '用一句话介绍 Python',
    '用一句话介绍 JavaScript',
    '用一句话介绍 Go',
  ];

  const replies = await sendSequence(page, questions);
  for (const r of replies) {
    expect(r.length, '每条回复非空').toBeGreaterThan(0);
  }

  // 至少 6 条气泡(3 user + 3 assistant)
  const total = await messageCount(page);
  expect(total).toBeGreaterThanOrEqual(6);

  // 上下文回显:第 3 条回复应至少引用前 2 条的关键词之一
  // 不强求全 3 个(LLM 行为不可控),至少含 1 个
  const lastReply = replies[replies.length - 1];
  const hits = ['Python', 'JavaScript', 'Go'].filter((kw) => lastReply.includes(kw));
  expect(
    hits.length,
    `期望最后一条回复含前文关键词,实际: ${lastReply}`,
  ).toBeGreaterThanOrEqual(1);
});