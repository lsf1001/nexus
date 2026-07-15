/**
 * Composer + 按钮 + Shift+Enter 锁测试 — 2026-07-16 第九轮 UI 重设计。
 *
 * WHY:Claude Desktop / ChatGPT 的 composer 都有 + 按钮(附件 / 截图 / 选 skill),
 * 第八轮 composer 缺这个发现,用户想附加内容没入口。第九轮加:
 *   1. composer 内部左下角 + 按钮(占位,无点击行为)
 *   2. Shift+Enter 行为已有(用 useChatAreaActions 验)
 *
 * 注:Enter 行为 = useChatAreaActions.handleKeyDown 的责任,Composer 只把
 * 事件透传。Composer 单测只能锁结构(有 + 按钮)+ Shift+Enter 透传。
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { useRef } from 'react';
import { Composer } from '../Composer';

function Harness({ onKeyDown }: { onKeyDown: (e: React.KeyboardEvent) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  return (
    <Composer
      value="test"
      onChange={() => {}}
      onSubmit={() => {}}
      onKeyDown={onKeyDown}
      placeholder="placeholder"
      disabled={false}
      isLoading={false}
      onStop={() => {}}
      inputRef={ref}
    />
  );
}

describe('Composer 第九轮 (+ 按钮 + 键盘透传)', () => {
  it('渲染 + 占位按钮 (左下角,placeholder)', () => {
    const { container } = render(<Harness onKeyDown={() => {}} />);
    const plusBtn = container.querySelector('button.composer-plus');
    expect(plusBtn, '+ 按钮必须存在 (.composer-plus)').not.toBeNull();
  });

  it('Shift+Enter 透传 onKeyDown (不内部截)', () => {
    const onKeyDown = vi.fn();
    const { container } = render(<Harness onKeyDown={onKeyDown} />);
    const ta = container.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true });
    expect(onKeyDown).toHaveBeenCalledTimes(1);
  });

  it('流期间显示 stop 按钮(不发 send 按钮)', () => {
    const onStop = vi.fn();
    function StopHarness() {
      const ref = useRef<HTMLTextAreaElement>(null);
      return (
        <Composer
          value="x"
          onChange={() => {}}
          onSubmit={() => {}}
          onKeyDown={() => {}}
          placeholder="p"
          disabled={false}
          isLoading={true}
          onStop={onStop}
          inputRef={ref}
        />
      );
    }
    const { container } = render(<StopHarness />);
    const stopBtn = container.querySelector('button.stop-button');
    expect(stopBtn).not.toBeNull();
    const sendBtn = container.querySelector('button.send-button:not(.stop-button)');
    expect(sendBtn).toBeNull();
    stopBtn!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(onStop).toHaveBeenCalled();
  });
});