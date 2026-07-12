/**
 * useStore partialize 单元测试 — node:test 零依赖。
 *
 * 核心约束:partialize 必须只列出 uiPrefs 切片字段(darkMode /
 * showThinking),防止业务字段(conversationMessages / channelInbox /
 * pendingConfirmation 等)被误写进 localStorage。
 *
 * 测试技巧:无法直接 require useStore.ts(无 tsx),改为镜像
 * partialize 函数并断言行为一致 — 若 store/index.ts 改了字段列表,
 * 这里要同步更新,作为约定。
 *
 * 运行:`npm run test:unit`
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

/** 与 store/index.ts 的 partialize 保持同步;若改了,这里要同步。 */
function partialize(state) {
  return {
    darkMode: state.darkMode,
    showThinking: state.showThinking,
  };
}

const FULL_STATE = {
  // uiPrefs
  darkMode: true,
  showThinking: false,
  // wsStatus
  wsConnected: true,
  wsStatus: 'connected',
  reconnectAttempts: 3,
  // conversations
  conversationMessages: [{ id: 'm1', role: 'user', content: 'secret payload' }],
  models: [{ id: 'gpt-4', name: 'GPT-4' }],
  currentModelId: 'gpt-4',
  modelName: 'GPT-4',
  isLoading: true,
  // channels
  channelInbox: { wechat: [{ id: 'w1', user_id: 'u1', content: 'private msg', timestamp: 1 }] },
  pendingConfirmation: { interruptId: 'i1', eventId: 1, actions: [] },
};

test('partialize 只输出 darkMode 和 showThinking', () => {
  const out = partialize(FULL_STATE);
  assert.deepEqual(out, { darkMode: true, showThinking: false });
});

test('partialize 不泄露 conversationMessages', () => {
  const out = partialize(FULL_STATE);
  assert.equal('conversationMessages' in out, false);
});

test('partialize 不泄露 channelInbox', () => {
  const out = partialize(FULL_STATE);
  assert.equal('channelInbox' in out, false);
});

test('partialize 不泄露 pendingConfirmation', () => {
  const out = partialize(FULL_STATE);
  assert.equal('pendingConfirmation' in out, false);
});

test('partialize 不泄露 isLoading / wsConnected / reconnectAttempts', () => {
  const out = partialize(FULL_STATE);
  for (const key of ['isLoading', 'wsConnected', 'wsStatus', 'reconnectAttempts', 'models', 'currentModelId', 'modelName']) {
    assert.equal(key in out, false, `${key} 不应被持久化`);
  }
});

test('partialize 输出字段数 = 2', () => {
  assert.equal(Object.keys(partialize(FULL_STATE)).length, 2);
});

test('partialize 默认值保持(false/true)', () => {
  assert.deepEqual(partialize({ darkMode: false, showThinking: true }), {
    darkMode: false,
    showThinking: true,
  });
});