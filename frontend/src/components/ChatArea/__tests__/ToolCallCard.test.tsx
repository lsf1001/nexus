/**
 * ToolCallCard 单测 — 2026-07-16 第九轮 UI 重设计。
 *
 * WHY:Claude Desktop / ChatGPT 把 tool 调用透明化展示在消息流,让用户看到
 * agent 在调什么工具、参数是什么、结果怎样。第八轮这些帧是 noop,第九轮
 * 起新增 ToolCallCard 组件 + 把 wsHandlers.tool_call/tool_result 接到 store。
 *
 * 契约:
 *   - 默认折叠(只露 name + state)
 *   - 点 toggle → 展开 args / result
 *   - state: running → success → error 三态颜色区分
 *   - args 用 <code> JSON 序列化展示
 *   - result 用 <pre> 纯文本展示
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { ToolCallCard } from '../ToolCallCard';
import { useStore } from '../../../store';
import { useToastStore } from '../../../store/useToast';
import type { ToolCall } from '../../../types';

function makeCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: 'tc-1',
    name: 'shell_run',
    state: 'success',
    args: { command: 'ls -la' },
    result: 'total 12\ndrwxr-xr-x 3 yxb staff 96 Jul 16 10:00 .\n',
    ...overrides,
  };
}

describe('ToolCallCard (第九轮)', () => {
  beforeEach(() => {
    useStore.getState().clearArtifacts();
    useStore.getState().setArtifactsCollapsed(true);
  });
  it('默认折叠 — 只显示 name + state,toggle 标 ▸', () => {
    const { container } = render(<ToolCallCard call={makeCall()} />);
    const card = container.querySelector('.tool-call-card');
    expect(card).not.toBeNull();
    expect(card?.textContent).toContain('shell_run');
    // SPEC:中文 state label(running / success / error → 运行中 / 成功 / 失败)
    expect(card?.textContent).toContain('成功');
    // 默认不显示 args / result
    expect(container.querySelector('.tool-call-code-block')).toBeNull();
    expect(container.querySelector('.tool-call-result')).toBeNull();
  });

  it('点 toggle → 展开 args + result', () => {
    const { container } = render(<ToolCallCard call={makeCall()} />);
    const toggle = container.querySelector('.tool-call-toggle') as HTMLElement;
    fireEvent.click(toggle);
    const args = container.querySelector('.tool-call-code-block');
    expect(args).not.toBeNull();
    expect(args?.textContent).toContain('ls -la');
    const result = container.querySelectorAll('.tool-call-code-block')[1];
    expect(result).not.toBeNull();
    expect(result?.textContent).toContain('total 12');
  });

  it('再点 toggle → 折叠', () => {
    const { container } = render(<ToolCallCard call={makeCall()} />);
    const toggle = container.querySelector('.tool-call-toggle') as HTMLElement;
    fireEvent.click(toggle); // 展开
    fireEvent.click(toggle); // 折叠
    expect(container.querySelector('.tool-call-code-block')).toBeNull();
  });

  it('state=running → 加 .is-running 类', () => {
    const { container } = render(<ToolCallCard call={makeCall({ state: 'running' })} />);
    const state = container.querySelector('.tool-call-state');
    expect(state?.classList.contains('is-running')).toBe(true);
  });

  it('state=error → 加 .is-error 类', () => {
    const { container } = render(<ToolCallCard call={makeCall({ state: 'error' })} />);
    const state = container.querySelector('.tool-call-state');
    expect(state?.classList.contains('is-error')).toBe(true);
  });

  it('没 result 时不渲染 result 区块(运行中)', () => {
    const { container } = render(
      <ToolCallCard call={makeCall({ state: 'running', result: undefined })} />
    );
    const toggle = container.querySelector('.tool-call-toggle') as HTMLElement;
    fireEvent.click(toggle);
    // 只有 args 一个 CodeBlock(result 区块整个不渲染)
    expect(container.querySelectorAll('.tool-call-code-block')).toHaveLength(1);
  });

  it('args 序列化成 JSON 字符串(code 元素)', () => {
    const { container } = render(
      <ToolCallCard
        call={makeCall({ args: { command: 'echo', cwd: '/tmp' } })}
      />
    );
    const toggle = container.querySelector('.tool-call-toggle') as HTMLElement;
    fireEvent.click(toggle);
    const args = container.querySelector('.tool-call-code-block code');
    expect(args).not.toBeNull();
    const parsed = JSON.parse(args!.textContent!);
    expect(parsed.command).toBe('echo');
    expect(parsed.cwd).toBe('/tmp');
  });

  // ─── 第十轮:ToolCallCard → Artifacts 联动 ───

  it('非 file-class 工具(shell_run)不显示联动链接', () => {
    const { container } = render(<ToolCallCard call={makeCall()} />);
    fireEvent.click(container.querySelector('.tool-call-toggle') as HTMLElement);
    expect(container.querySelector('.tool-call-open-artifact')).toBeNull();
  });

  it('file-class 工具 + result ≥ 30 字符 → 显示"→ 在右侧查看"', () => {
    const code = 'def hello():\n    return "hi from nexus"\n';
    const { container } = render(
      <ToolCallCard
        call={makeCall({
          id: 'tc-py',
          name: 'edit_file',
          args: { path: 'hello.py' },
          result: code,
        })}
      />
    );
    fireEvent.click(container.querySelector('.tool-call-toggle') as HTMLElement);
    const btn = container.querySelector('.tool-call-open-artifact');
    expect(btn).not.toBeNull();
    expect(btn?.textContent).toContain('在右侧查看');
  });

  it('点联动按钮 → pushArtifact 自动激活 + 展开', () => {
    const code = 'def hello():\n    return "hi from nexus"\n';
    const { container } = render(
      <ToolCallCard
        call={makeCall({
          id: 'tc-py',
          name: 'edit_file',
          args: { path: 'hello.py' },
          result: code,
        })}
      />
    );
    fireEvent.click(container.querySelector('.tool-call-toggle') as HTMLElement);
    fireEvent.click(container.querySelector('.tool-call-open-artifact') as HTMLElement);
    const state = useStore.getState();
    expect(state.artifacts).toHaveLength(1);
    expect(state.artifacts[0]?.filename).toBe('hello.py');
    expect(state.artifacts[0]?.kind).toBe('code');
    expect(state.artifacts[0]?.language).toBe('python');
    expect(state.activeArtifactId).toBe('tc-py');
    expect(state.artifactsCollapsed).toBe(false);
  });

  it('.md 文件 → markdown kind', () => {
    const md = '# Hello\n\nThis is a sample doc with enough length to pass the threshold.\n';
    const { container } = render(
      <ToolCallCard
        call={makeCall({
          id: 'tc-md',
          name: 'write_md',
          args: { path: 'README.md' },
          result: md,
        })}
      />
    );
    fireEvent.click(container.querySelector('.tool-call-toggle') as HTMLElement);
    fireEvent.click(container.querySelector('.tool-call-open-artifact') as HTMLElement);
    const a = useStore.getState().artifacts[0];
    expect(a?.kind).toBe('markdown');
    expect(a?.filename).toBe('README.md');
  });

  it('state=running 不显示联动(还没出结果)', () => {
    const { container } = render(
      <ToolCallCard
        call={makeCall({ state: 'running', result: undefined })}
      />
    );
    fireEvent.click(container.querySelector('.tool-call-toggle') as HTMLElement);
    expect(container.querySelector('.tool-call-open-artifact')).toBeNull();
  });

  // ─── 第十一轮:ToolCallCard 内 JSON / 命令 / 文件代码块加复制按钮 ───

  describe('CodeBlock 复制按钮', () => {
    let pushSpy: ReturnType<typeof vi.spyOn>;
    let hadClipboard: boolean;

    beforeEach(() => {
      // mock navigator.clipboard.writeText — jsdom 默认没有
      hadClipboard = 'clipboard' in navigator && !!navigator.clipboard;
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: vi.fn().mockResolvedValue(undefined) },
        configurable: true,
        writable: true,
      });
      pushSpy = vi.spyOn(useToastStore.getState(), 'push');
    });

    afterEach(() => {
      if (hadClipboard) {
        // 恢复原始 clipboard(本次测试不能污染其他 spec)
        Object.defineProperty(navigator, 'clipboard', {
          value: { writeText: vi.fn().mockResolvedValue(undefined) },
          configurable: true,
          writable: true,
        });
      } else {
        Object.defineProperty(navigator, 'clipboard', {
          value: undefined,
          configurable: true,
          writable: true,
        });
      }
      pushSpy.mockRestore();
    });

    it('点 args 复制按钮 → 调 clipboard.writeText(argsJson) + 显示"已复制"气泡', () => {
      const { container } = render(<ToolCallCard call={makeCall()} />);
      fireEvent.click(container.querySelector('.tool-call-toggle') as HTMLElement);
      const copyBtn = container.querySelector(
        '.tool-call-code-block .code-copy-btn',
      ) as HTMLElement;
      expect(copyBtn).not.toBeNull();
      fireEvent.click(copyBtn);
      expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1);
      const calledWith = (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mock
        .calls[0]![0] as string;
      expect(calledWith).toContain('"command": "ls -la"');
      // "已复制" 气泡 1000ms 内可见
      expect(container.querySelector('.code-flash')?.textContent).toContain('已复制');
    });

    it('clipboard 抛错 → toast.warn 提示手动选择', async () => {
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: vi.fn().mockRejectedValue(new Error('Permission denied')) },
        configurable: true,
        writable: true,
      });
      const { container } = render(<ToolCallCard call={makeCall()} />);
      fireEvent.click(container.querySelector('.tool-call-toggle') as HTMLElement);
      const copyBtn = container.querySelector(
        '.tool-call-code-block .code-copy-btn',
      ) as HTMLElement;
      fireEvent.click(copyBtn);
      // microtask 队列跑完
      await Promise.resolve();
      await Promise.resolve();
      const warnCalls = pushSpy.mock.calls.filter((c) => c[0] === 'warn');
      expect(warnCalls.length).toBeGreaterThan(0);
      expect(warnCalls[0]?.[1] ?? '').toContain('复制失败');
    });
  });
});