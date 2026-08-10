/**
 * appendAssistantPatch placeholder leak 单测 — 2026-08-08 Round 6.2 修复。
 *
 * 根因:appendAssistantPatch 只往 last assistant 占位写 patch,从不清理。
 * WS 错误流(error 帧先于 final / 无 final 帧)中:
 *   1. 第一轮:pushUserAndPlaceholder → [user1, assistant{空占位}]
 *   2. 帧序:thinking → thinking → error(error 不写 store content)
 *   3. store 现状:[user1, assistant{thinking:'...', content:''}]
 *   4. 第二轮:用户再发 → pushUserAndPlaceholder → [user1, asst{orphan},
 *      user2, asst{new}]
 *   5. 帧序:thinking → thinking → chunk → final
 *   6. appendAssistantPatch 命中 last(asst{new}),orphan 留在列表里,渲染成
 *      "重复思考卡片 + 孤立你好"。
 *
 * 修复契约(error 帧到 / 兜底 final 没到时清理):
 *   - 若末尾是 assistant placeholder 且 content==='' && !thinking
 *     → 直接 pop 掉(用户从来没见过,无信息损失)
 *   - 若末尾 assistant 已有 thinking(用户能看见的痕迹)但 content===''
 *     → 在它的 content 写入 error 文案(产品反馈"上一轮没拿到回复"),
 *      不再泄漏到下一轮造成重复卡片
 *
 * 测试覆盖:
 *   - 空占位 → error 帧:被 pop
 *   - thinking-only 占位 → error 帧:content 被改写为错误文案(保留 thinking 留痕)
 *   - 有 content 占位 → error 帧:不动(已经是真实回复)
 *   - 没有占位 → error 帧:不动(appendAssistantPatch 不管这个场景,跳过)
 *   - 用户 stopped → error 帧:不动(尊重 stop gate,与其它 handler 一致)
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../../index';
import type { Message } from '../../../types';

function reset(): void {
  useStore.setState({
    conversationMessages: [],
    streamingPaused: false,
  });
}

function makeUserMsg(content: string): Message {
  return {
    id: `u-${content}`,
    role: 'user',
    content,
    createdAt: new Date('2026-08-08T00:00:00Z'),
  };
}

function makeAssistant(content: string, thinking?: string): Message {
  return {
    id: `a-${content}-${thinking ?? ''}`,
    role: 'assistant',
    content,
    thinking,
    createdAt: new Date('2026-08-08T00:00:00Z'),
  };
}

/** handleError 等价路径:模拟 wsHandlers 在 error 帧到达时的清理动作。
 *  修复后,handleError 会调一个新的 store action(命名:discardEmptyAssistantPlaceholder)。
 *  这里测试它的契约,不绑死命名 — 直接通过 store action 调用。 */
function simulateErrorFrame(errorText: string): void {
  // 修复后:handleError 调一个新的清理 action。这里用 store action 名字的
  // forward-compat 写法 — 测试时该 action 必须存在(编译期保证)。
  const fn = (useStore.getState() as unknown as Record<string, unknown>)
    .discardEmptyAssistantPlaceholder as
    | ((err: string) => void)
    | undefined;
  if (typeof fn !== 'function') {
    throw new Error(
      'discardEmptyAssistantPlaceholder 不存在 — handleError 还没接入清理逻辑',
    );
  }
  fn(errorText);
}

describe('placeholder leak 修复(error 帧清理)', () => {
  beforeEach(() => reset());

  it('空占位(无 content 无 thinking)+ error → 直接 pop,不留孤儿', () => {
    // 第一轮推完 user + 空占位后,thinking 帧从未到达(error 帧抢在所有 thinking 前)
    useStore.setState({
      conversationMessages: [makeUserMsg('你好'), makeAssistant('')],
    });

    simulateErrorFrame('模型暂时不可用');

    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0]?.role).toBe('user');
  });

  it('thinking-only 占位(用户能看见的思考痕迹)+ error → content 被改写为错误文案,thinking 保留', () => {
    useStore.setState({
      conversationMessages: [
        makeUserMsg('你好'),
        makeAssistant('', '正在识别你的意图…'),
      ],
    });

    simulateErrorFrame('上游 503');

    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(2);
    const last = msgs[1];
    expect(last?.role).toBe('assistant');
    expect(last?.content).toBe('上游 503');
    expect(last?.thinking).toBe('正在识别你的意图…');
  });

  it('已有 content 的占位 + error → 不动(避免覆盖已有真实回复)', () => {
    useStore.setState({
      conversationMessages: [
        makeUserMsg('你好'),
        makeAssistant('我收到了', '正在识别…'),
      ],
    });

    simulateErrorFrame('错误文案不应覆盖');

    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(2);
    expect(msgs[1]?.content).toBe('我收到了');
    expect(msgs[1]?.thinking).toBe('正在识别…');
  });

  it('末尾不是 assistant(empty msg list / user 收尾)+ error → 不动', () => {
    // 空列表
    simulateErrorFrame('err');
    expect(useStore.getState().conversationMessages).toHaveLength(0);

    // 末尾是 user(罕见:error 在 user msg 之前到达,defensive)
    useStore.setState({
      conversationMessages: [makeUserMsg('hi')],
    });
    simulateErrorFrame('err');
    expect(useStore.getState().conversationMessages).toHaveLength(1);
  });

  it('端到端:error 帧清理后再 pushUserAndPlaceholder,不会产生孤儿', () => {
    // 1) 第一轮完整流程
    useStore.setState({
      conversationMessages: [
        makeUserMsg('第一轮'),
        makeAssistant('', '第一轮的思考'),
      ],
    });
    simulateErrorFrame('第一轮失败');
    expect(useStore.getState().conversationMessages).toHaveLength(2);

    // 2) 用户发第二轮 — 模拟 pushUserAndPlaceholder 的效果(不在测试范围,直接构造最终态)
    //    关键断言:此时末尾已经不是前一轮 thinking-only 占位(已经被改写成错误文案),
    //    push 出来的 user + new placeholder 不会跟旧 thinking 混在一起。
    useStore.setState({
      conversationMessages: [
        ...useStore.getState().conversationMessages,
        makeUserMsg('第二轮'),
        makeAssistant(''),
      ],
    });

    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(4);
    expect(msgs[0]?.content).toBe('第一轮');
    expect(msgs[1]?.content).toBe('第一轮失败');
    expect(msgs[1]?.thinking).toBe('第一轮的思考');
    expect(msgs[2]?.content).toBe('第二轮');
    expect(msgs[3]?.content).toBe('');
  });

  it('streamingPaused=true 时,appendAssistantPatch 仍然 gate — discardEmptyAssistantPlaceholder 也尊重 stop', () => {
    // 用户点 stop 之后所有写入动作都应被尊重 — 包括 placeholder 清理动作。
    // 因为:
    //   1. handleStop 在 content 末尾追加 '[已停止]' marker,这条路径走的是
    //      setConversationMessages(不走 appendAssistantPatch gate),本身能写
    //   2. 但 streamingPaused=true 之后还有可能收到 error 帧,如果 error 帧
    //      触发清理,会把 [已停止] 路径留下的占位抹掉,用户失去 stop 反馈
    // 所以 discardEmptyAssistantPlaceholder 必须看 streamingPaused gate,与
    // appendAssistantPatch 的 gate 行为一致。
    useStore.setState({ streamingPaused: true });
    useStore.setState({
      conversationMessages: [
        makeUserMsg('hi'),
        makeAssistant('', '我被 stop 了'),
      ],
    });
    simulateErrorFrame('stopped');
    const msgs = useStore.getState().conversationMessages;
    // streamingPaused=true → 不动占位,留给后续 handleStop / next pushUserAndPlaceholder 处理
    expect(msgs).toHaveLength(2);
    expect(msgs[1]?.content).toBe('');
    expect(msgs[1]?.thinking).toBe('我被 stop 了');
  });

  it('streamingPaused=true 且 placeholder 已有 [已停止] marker → error 帧不清理(尊重 stop)', () => {
    // 真实场景:用户点 stop → handleStop 已在 content 末尾追加 '\n\n_[已停止]_',
    // 之后流端发 error 帧(服务端 stream 还没真停)。此时 error 帧到达不能清
    // 占位,否则会把 [已停止] 抹掉,用户看不到任何反馈 — journey-stop-mid-stream
    // spec 走的就是这条路径。
    useStore.setState({ streamingPaused: true });
    useStore.setState({
      conversationMessages: [
        makeUserMsg('hi'),
        makeAssistant('部分内容\n\n_[已停止]_', '思考过程'),
      ],
    });
    simulateErrorFrame('err should not erase stop marker');
    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(2);
    // content 完全不动 — 已经有真实内容 + 停止标记
    expect(msgs[1]?.content).toBe('部分内容\n\n_[已停止]_');
    expect(msgs[1]?.thinking).toBe('思考过程');
  });

  it('streamingPaused=true 且 placeholder content=="" → 不清理(尊重 stop,留给 [已停止] 路径)', () => {
    // 边界:用户立刻 stop 在首个 chunk 之前 — 占位 content 仍空,thinking 可能
    // 已经有了。此时 error 帧到达,如果按原契约清掉占位 → 用户连"上一轮被 stop"
    // 的反馈都看不到(原本由 [已停止] marker 表达,marker 是 handleStop 后追加,
    // 但如果 error 帧把空占位 pop 了,marker 没机会写)。所以 stop gate 必须生效:
    // streamingPaused=true 时不动。
    useStore.setState({ streamingPaused: true });
    useStore.setState({
      conversationMessages: [
        makeUserMsg('hi'),
        makeAssistant('', '刚刚开始思考'),
      ],
    });
    simulateErrorFrame('服务端 503');
    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(2);
    // content 保持空,thinking 保留 — 用户没看到过任何 chunk,error 帧不该 pop
    expect(msgs[1]?.content).toBe('');
    expect(msgs[1]?.thinking).toBe('刚刚开始思考');
  });
});