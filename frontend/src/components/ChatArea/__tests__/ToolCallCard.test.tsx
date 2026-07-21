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
import { describe, expect, it, beforeEach } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { ToolCallCard } from '../ToolCallCard';
import { useStore } from '../../../store';
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
    expect(container.querySelector('.tool-call-args')).toBeNull();
    expect(container.querySelector('.tool-call-result')).toBeNull();
  });

  it('点 toggle → 展开 args + result', () => {
    const { container } = render(<ToolCallCard call={makeCall()} />);
    const toggle = container.querySelector('.tool-call-toggle') as HTMLElement;
    fireEvent.click(toggle);
    const args = container.querySelector('.tool-call-args');
    expect(args).not.toBeNull();
    expect(args?.textContent).toContain('ls -la');
    const result = container.querySelector('.tool-call-result');
    expect(result).not.toBeNull();
    expect(result?.textContent).toContain('total 12');
  });

  it('再点 toggle → 折叠', () => {
    const { container } = render(<ToolCallCard call={makeCall()} />);
    const toggle = container.querySelector('.tool-call-toggle') as HTMLElement;
    fireEvent.click(toggle); // 展开
    fireEvent.click(toggle); // 折叠
    expect(container.querySelector('.tool-call-args')).toBeNull();
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
    expect(container.querySelector('.tool-call-args')).not.toBeNull();
    expect(container.querySelector('.tool-call-result')).toBeNull();
  });

  it('args 序列化成 JSON 字符串(code 元素)', () => {
    const { container } = render(
      <ToolCallCard
        call={makeCall({ args: { command: 'echo', cwd: '/tmp' } })}
      />
    );
    const toggle = container.querySelector('.tool-call-toggle') as HTMLElement;
    fireEvent.click(toggle);
    const args = container.querySelector('.tool-call-args code');
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
});