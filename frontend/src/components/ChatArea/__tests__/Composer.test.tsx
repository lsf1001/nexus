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
 *
 * 第十三轮(2026-07-24)新增:paste / drop / + 按钮 / onSubmit 收 ids。
 * useAttachments 内部调 fetch — 测试用 vi.spyOn(globalThis, 'fetch') mock 掉,
 * 避免 jsdom 网络调用 + 跟 hook 单测保持一致 mock 风格。
 *
 * Review 修复(2026-07-30)新增:dragenter/dragleave 深度计数防子元素冒泡抖动。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, waitFor } from '@testing-library/react';
import { useRef } from 'react';
import { Composer } from '../Composer';
import { useStore } from '@/store';

function Harness({
  onKeyDown,
  onSubmit,
  value = 'test',
}: {
  onKeyDown: (e: React.KeyboardEvent) => void;
  onSubmit?: (ids: string[]) => void;
  value?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  return (
    <Composer
      value={value}
      onChange={() => {}}
      onSubmit={onSubmit ?? (() => {})}
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

/**
 * 第十三轮:Composer 接入 useAttachments 的 4 个交互路径。
 *   - + 按钮 click 触发 hidden <input type="file"> click
 *   - textarea paste → clipboard.files → useAttachments.addFiles → attachment 列表非空
 *   - Composer 整区 drop → dataTransfer.files → useAttachments.addFiles → attachment 列表非空
 *   - onSubmit 被调时透传 uploadedServerIds(本测试只断言 onSubmit 触发,server id 列表由
 *     useAttachments.test.ts 单测覆盖;此处仅保证 onSubmit 仍能被发送按钮触发,id 数组形式)
 *
 * 边界:fetch mock 默认返 201 + server id;attachment 上传走真 hook 路径,
 * 测试只断言"列表非空"避免脆弱。
 */
describe('Composer 第十三轮 (附件接入)', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            id: 'att_xxx',
            project_id: 'default',
            original_name: 'f',
            stored_filename: 'f',
            file_path: '/x',
            mime: 'text/plain',
            size: 1,
            uploaded_at: '2026-01-01',
          }),
          { status: 201 },
        ),
      );
    useStore.setState({ activeProjectId: 'default' });
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it('+ 按钮 click 触发 hidden file input 的 click (file picker)', () => {
    const { container } = render(<Harness onKeyDown={() => {}} />);
    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    expect(input, 'hidden file input 必须存在').not.toBeNull();
    const clickSpy = vi.spyOn(input, 'click');
    const plusBtn = container.querySelector(
      'button.composer-plus',
    ) as HTMLButtonElement;
    expect(plusBtn).not.toBeNull();
    fireEvent.click(plusBtn);
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it('textarea paste 文件 → 调 useAttachments.addFiles', async () => {
    const { container } = render(<Harness onKeyDown={() => {}} />);
    const ta = container.querySelector('textarea') as HTMLTextAreaElement;
    const file = new File(['hello'], 'note.txt', { type: 'text/plain' });
    const dt = {
      files: [file],
      getData: () => '',
    } as unknown as DataTransfer;
    fireEvent.paste(ta, { clipboardData: dt });
    // 等 useAttachments 内部 setState 完成
    await waitFor(() => {
      // 路径必须含 /api/attachments(useAttachments 走 apiFetch,
      // 它内部 resolveApiUrl 会把 'http://localhost:...' 补全)
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/api/attachments'),
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('Composer 整区 drop 文件 → 调 useAttachments.addFiles + 拖拽高亮类名切换', async () => {
    const { container } = render(<Harness onKeyDown={() => {}} />);
    const composer = container.querySelector('.composer') as HTMLDivElement;
    expect(composer).not.toBeNull();

    const file = new File(['hello'], 'note.txt', { type: 'text/plain' });
    const dt = {
      files: [file],
    } as unknown as DataTransfer;
    // dragover → is-drag-over 类名出现
    fireEvent.dragOver(composer, { dataTransfer: dt });
    expect(composer.className).toContain('is-drag-over');
    // drop → 类名移除 + 调 fetch
    fireEvent.drop(composer, { dataTransfer: dt });
    expect(composer.className).not.toContain('is-drag-over');
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/api/attachments'),
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('点 send 按钮触发 onSubmit (验证 onSubmit 签名扩展后调用链仍通)', () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <Harness onKeyDown={() => {}} onSubmit={onSubmit} value="hi" />,
    );
    const sendBtn = container.querySelector(
      'button.send-button:not(.stop-button)',
    ) as HTMLButtonElement;
    expect(sendBtn).not.toBeNull();
    fireEvent.click(sendBtn);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    // 第一参数是 attachment ids 数组(空,因没附件)
    const callArgs = onSubmit.mock.calls[0];
    expect(Array.isArray(callArgs?.[0])).toBe(true);
  });

  /**
   * dragenter/dragleave 深度计数:光标从 Composer 移到其子元素(textarea)时,
   * 浏览器派发的是"子元素 dragenter + 父元素 dragleave"一对冒泡事件。
   * 只看 dragleave 就撤高亮会让边框抖动 —— 这里断言高亮在此期间保持。
   */
  it('子元素冒泡的 dragleave 不撤高亮(counter 未归零)', () => {
    const { container } = render(<Harness onKeyDown={() => {}} />);
    const composer = container.querySelector('.composer') as HTMLDivElement;
    const ta = container.querySelector('textarea') as HTMLTextAreaElement;

    // 拖进 Composer → 高亮
    fireEvent.dragEnter(composer);
    expect(composer.className).toContain('is-drag-over');

    // 拖进子元素 textarea(冒泡到 composer 记 +1),同时 composer 收到 dragleave(-1)
    fireEvent.dragEnter(ta);
    fireEvent.dragLeave(composer);
    expect(
      composer.className,
      'counter 仍 > 0,高亮必须保持(否则抖动)',
    ).toContain('is-drag-over');

    // 真正离开整区:最后一个 dragleave 让 counter 归零 → 撤高亮
    fireEvent.dragLeave(ta);
    expect(composer.className).not.toContain('is-drag-over');
  });
});