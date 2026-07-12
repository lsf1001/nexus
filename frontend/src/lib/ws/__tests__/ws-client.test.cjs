/**
 * WsClient 纯函数单测 — node:test(Node.js 内置,零依赖)。
 *
 * 为什么不用 vitest:本项目无 vitest(也没装 tsx/ts-node),避免拉 30+ 依赖。
 * computeReconnectDelay 是无副作用纯函数,行为可单测;类行为(jitter 时序
 * / 重连退避)需要 mock WebSocket,放到后续 vitest 阶段(见 task #21)。
 *
 * 运行:`npm run test:unit`
 *
 * 双份实现 trade-off:测试用 .cjs 避免 tsx,镜像 WsClient.ts 的纯函数;
 * 若 WsClient.ts 改了公式,这里要同步更新。
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

function computeReconnectDelay(attempt, policy, rng = Math.random) {
  const exponential = Math.min(policy.maxDelayMs, policy.baseDelayMs * 2 ** attempt);
  const jitterRange = policy.jitterRatio * exponential;
  return exponential + (rng() * 2 - 1) * jitterRange;
}

const POLICY = { baseDelayMs: 1000, maxDelayMs: 30000, jitterRatio: 0.3 };

test('attempt=0 rng=0.5 → 1000ms(jitter 中位数)', () => {
  assert.equal(computeReconnectDelay(0, POLICY, () => 0.5), 1000);
});

test('attempt=0 rng=1 → +30% 上限', () => {
  assert.equal(computeReconnectDelay(0, POLICY, () => 1), 1300);
});

test('attempt=0 rng=0 → -30% 下限', () => {
  assert.equal(computeReconnectDelay(0, POLICY, () => 0), 700);
});

test('attempt=4 → 1000*2^4 = 16000ms', () => {
  assert.equal(computeReconnectDelay(4, { ...POLICY, jitterRatio: 0 }, () => 0.5), 16000);
});

test('attempt=10 → 截断到 maxDelayMs=30000', () => {
  assert.equal(computeReconnectDelay(10, { ...POLICY, jitterRatio: 0 }, () => 0.5), 30000);
});

test('1000 次 Math.random 样本均落在 ±30% 内', () => {
  for (let i = 0; i < 1000; i++) {
    const d = computeReconnectDelay(0, POLICY);
    assert.ok(d >= 700 && d <= 1300, `delay=${d} 越界`);
  }
});

test('attempt=0..8 退避序列(jitter=0) 累计 151000ms ~ 2.5min', () => {
  let total = 0;
  for (let attempt = 0; attempt < 9; attempt++) {
    total += computeReconnectDelay(attempt, { ...POLICY, jitterRatio: 0 }, () => 0.5);
  }
  // attempt 0..4: 1000+2000+4000+8000+16000 = 31000
  // attempt 5..8: 4 * 30000 = 120000(maxDelay 截断)
  // 合计 151000ms
  assert.equal(total, 151000);
});