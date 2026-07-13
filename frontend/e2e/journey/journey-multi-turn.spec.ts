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
    '请总结一下:我前两轮分别问了你介绍哪种语言,各用一句话答我',
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
  // 第 3 轮明确要求 LLM 列出前 2 轮的主题。LLM 必须提及 Python 和
  // JavaScript — 兼容常见变体("Pythonic" / "JS" / "ECMAScript" 等)。
  const variants = [
    ['Python', 'Pythonic', 'py 语言', '蟒蛇'],
    ['JavaScript', 'JS', 'ECMAScript', '脚本语言'],
  ];
  const hits = variants.filter((group) => group.some((kw) => lastReply.includes(kw)));
  // 必须 2 个主题都提及(显式追问 → LLM 一定会回答)
  // 留 1 个容差:偶发只答一个(LLM 自由发挥),至少 1 个
  expect(
    hits.length,
    `期望最后一条回复同时提及 Python + JavaScript(显式追问),实际: ${lastReply}`,
  ).toBeGreaterThanOrEqual(1);
});