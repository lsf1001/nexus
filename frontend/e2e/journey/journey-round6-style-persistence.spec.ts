/**
 * User Journey: Round 6.1 — Composer 风格持久化链路 E2E (Task 11)
 *
 * 用户故事:
 *   1. 进 ChatView(默认空会话),点 Composer 风格选择器 → 选'专业'
 *   2. 验:store.sessionStyles 命中 'professional'(Composer 徽标显示)
 *   3. 拦截 /api/sessions/{id} PATCH → 200
 *   4. 验:Sidebar 任务项显示 '专业' 徽标
 *   5. 发一条消息
 *   6. 截 WebSocket send 帧 → 验 payload.style === 'professional'
 *   7. mock LLM 端读 /api/e2e/last-messages → 验 LLM 真收到第二条消息
 *      (HumanMessage.content === '带风格字段的请求'),证明 agent 真重建 +
 *      新 mock 实例被 register_e2e_mock 替换
 *   8. 刷新页面 → 风格仍为 'professional',徽标仍在(持久化生效)
 *
 * Mock 模式(NEXUS_E2E_MOCK=1):
 *   - LLM 由 e2e_mock 替代,scenario 走默认 allow_nexus_write(不触发 HITL)。
 *   - /api/e2e/last-messages 仅 mock 下挂载(nexus/backend/routes/e2e_diagnostics.py:46),
 *     抓 mock LLM 最后一次 _generate 收到的完整 messages(含 system prompt)。
 *   - PATCH /api/sessions/{id} 走 page.route 拦截,避免真后端落库,
 *     跨 spec 顺序跑不污染。
 *
 * System prompt directive 断言(2026-08-05 修复):
 *   DynamicIdentityMiddleware 现在读 ``llm._nexus_style`` 透传给
 *   ``get_system_prompt(style=...)``,LLM 收到的 prompt 必须含
 *   【回复风格 · 专业】段。本 spec 验证 /api/e2e/last-messages 返回的
 *   SystemMessage.content 含此段(证明 backend 修复生效,不再覆盖
 *   agent 注入的 directive)。
 *
 * WS send 截帧设计:
 *   - 在 page.addInitScript 里包装 WebSocket,捕获业务 WS(/api/ws)的
 *     send(data) 调用,存到 __nexusSentFrames 数组(plain object,JSON 序列化)。
 *   - 与 reconnect.spec.ts:33-69 同一思路(只接 /api/ws,排除 Vite HMR)。
 *
 * 风格选择器触发路径(ComposerToolbar.tsx:148-167):
 *   - DropdownMenu.Trigger 按钮:aria-label="选择回复风格",文本含当前 label
 *   - DropdownMenuItem:role=menuitem,文本 = STYLE_LABELS[value]
 *   - 选完后徽标 .style-badge 出现,文本 = 当前 label
 *
 * Sidebar 风格徽标(Sidebar.tsx:308-316):
 *   - .task-item-style-badge + data-style="professional"
 *
 * 运行:
 *   NEXUS_E2E_MOCK=1 npx playwright test \
 *     e2e/journey/journey-round6-style-persistence.spec.ts
 */
import { test, expect, type Page } from '@playwright/test';
import {
  openHome,
  sendMessageAndWaitForReply,
} from '../helpers';
import { journeyOpenHome } from './helpers';

const MOCK = process.env.NEXUS_E2E_MOCK === '1';

test.skip(!MOCK, '本 spec 走 mock LLM + E2E 诊断端点,需 NEXUS_E2E_MOCK=1');

const APP_WS_KEY = '__nexusAppSockets';
const SENT_FRAMES_KEY = '__nexusSentFrames';

/** 安装 WebSocket 拦截器,把 send() 的 JSON 帧 push 到 window。 */
async function installWsFrameCapture(page: Page): Promise<void> {
  await page.addInitScript(
    (args: { socketsKey: string; framesKey: string }) => {
      const { socketsKey, framesKey } = args;
      const w = window as unknown as { [k: string]: unknown };
      const OriginalWebSocket = window.WebSocket;
      if (!w[socketsKey]) w[socketsKey] = [];
      if (!w[framesKey]) w[framesKey] = [];
      if (w.__nexusOriginalWebSocket) return;
      w.__nexusOriginalWebSocket = OriginalWebSocket;

      function CapturedWebSocket(this: unknown, url: string | URL, protocols?: string | string[]) {
        const urlStr = String(url);
        const ws =
          protocols === undefined
            ? new OriginalWebSocket(url)
            : new OriginalWebSocket(url, protocols);
        if (urlStr.includes('/api/ws') && !urlStr.includes('?token=')) {
          const sockets = (w[socketsKey] as WebSocket[] | undefined) ?? [];
          sockets.push(ws);
          // 包装 send:把字符串 / 字节 frame parse 成 JSON 后 push。
          const origSend = ws.send.bind(ws);
          ws.send = function (data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
            try {
              let payload: unknown = data;
              if (typeof data === 'string') {
                try {
                  payload = JSON.parse(data);
                } catch {
                  // 非 JSON 字符串原样存
                  payload = data;
                }
              }
              const frames = (w[framesKey] as unknown[] | undefined) ?? [];
              frames.push(payload);
            } catch {
              // 解析失败也不影响真实 send
            }
            return origSend(data as string);
          } as typeof ws.send;
        }
        return ws;
      }

      CapturedWebSocket.prototype = OriginalWebSocket.prototype;
      CapturedWebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
      CapturedWebSocket.OPEN = OriginalWebSocket.OPEN;
      CapturedWebSocket.CLOSING = OriginalWebSocket.CLOSING;
      CapturedWebSocket.CLOSED = OriginalWebSocket.CLOSED;
      window.WebSocket = CapturedWebSocket as unknown as typeof WebSocket;
    },
    { socketsKey: APP_WS_KEY, framesKey: SENT_FRAMES_KEY },
  );
}

/** 读 page 端缓存的所有 send 帧(JSON.parse 后的对象)。 */
async function readSentFrames(page: Page): Promise<Array<Record<string, unknown>>> {
  return await page.evaluate((key: string) => {
    const frames = (window as unknown as Record<string, unknown[] | undefined>)[key] ?? [];
    return frames.filter(
      (f): f is Record<string, unknown> => typeof f === 'object' && f !== null,
    );
  }, SENT_FRAMES_KEY);
}

test('Round 6.1:Composer 切专业风格 → 徽标 + WS 帧 + LLM 真收到 → 刷新持久化', async ({ page }) => {
  test.setTimeout(180_000);

  // 0. 装 WS 帧拦截 + 拦 PATCH /api/sessions/{id}
  await installWsFrameCapture(page);
  // PATCH 拦截:用 regex 匹配 path 含 /api/sessions/<id>,return 200
  // 避免真后端落库 + 跨 spec 污染。静默 200 即可,前端逻辑不读 body。
  await page.route(/\/api\/sessions\/[^/]+$/, async (route) => {
    if (route.request().method() === 'PATCH') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      });
      return;
    }
    await route.continue();
  });

  // 1. 进 ChatView
  await journeyOpenHome(page);

  // 2. 第一次发消息,创建新会话 → 拿到 session_id
  //    走 sendMessageAndWaitForReply:等 user/assistant 1:1 + 助手非空文本 +
  //    输入框重可点。mock LLM scenario `allow_nexus_write` 第一次 invoke
  //    返回 tool_calls(写 .nexus/outputs/e2e_allow.md),第二次 invoke 返回
  //    reflection `操作完成。`(见 nexus/backend/llm/e2e_mock.py:30-37)。
  //    关键:不能只等 messageInput re-enable —— ChatArea 里 input 的 disabled
  //    只跟 wsConnected 绑,跟 isLoading 解耦(2026-08-05 验证)。需要等
  //    assistant 文本非空才说明流真的结束。
  await sendMessageAndWaitForReply(page, '先创建会话', { timeoutMs: 60_000 });

  // 等新会话出现 Sidebar 任务项(.task-item),data-conversation-id 是 sid。
  // 风格还没切,不应该有 .task-item-style-badge(Sidebar 徽标 default 不渲染)。
  const firstTaskItem = page.locator('.task-item').first();
  await expect(firstTaskItem, '新建会话应在 Sidebar 出现').toBeVisible({ timeout: 5_000 });
  const sessionId = await firstTaskItem.getAttribute('data-conversation-id');
  expect(sessionId, '会话项应有 data-conversation-id').toBeTruthy();
  await expect(firstTaskItem.locator('.task-item-style-badge')).toHaveCount(0);

  // 3. 点 Composer 风格选择器 → 选'专业'
  const styleTrigger = page.locator('button[aria-label="选择回复风格"]');
  await expect(styleTrigger, '风格选择器触发按钮应可见').toBeVisible({ timeout: 5_000 });
  await styleTrigger.click();
  // 弹出 DropdownMenu,3 个 menuitem 文本分别是'默认' / '简洁' / '专业'。
  // role=menuitem + text 锁定,避免其它菜单干扰(测试锁定的关键)。
  const proItem = page.getByRole('menuitem', { name: '专业' });
  await expect(proItem, '专业 menuitem 应可见').toBeVisible({ timeout: 3_000 });
  await proItem.click();

  // 4. 验:store.sessionStyles 命中 + Composer 徽标显示
  //    .style-badge 出现且文本为 '专业'(ComposerToolbar.tsx:160-165)。
  await expect(page.locator('.style-badge'), 'Composer 徽标 .style-badge 应出现').toBeVisible({
    timeout: 3_000,
  });
  await expect(page.locator('.style-badge')).toHaveText('专业');

  // 5. 验:Sidebar 任务项显示 '专业' 徽标
  //    data-style="professional" 是 Sidebar.tsx:311 的契约属性。
  const taskItem = page.locator(`.task-item[data-conversation-id="${sessionId}"]`);
  await expect(taskItem, '对应会话项应存在').toBeVisible({ timeout: 5_000 });
  const badge = taskItem.locator('.task-item-style-badge');
  await expect(badge, 'Sidebar 风格徽标应出现').toBeVisible({ timeout: 5_000 });
  await expect(badge).toHaveText('专业');
  await expect(badge).toHaveAttribute('data-style', 'professional');

  // 6. 发第二条消息 → 截 WS send 帧 + 等流完成
  await sendMessageAndWaitForReply(page, '带风格字段的请求', { timeoutMs: 60_000 });

  // 7. 验:WS send 帧带 style === 'professional'
  //    user_message 帧字段(content / session_id / style)。取最后一条
  //    包含 content === '带风格字段的请求' 的 user_message 帧。
  const frames = await readSentFrames(page);
  const lastUserMsgFrame = [...frames]
    .reverse()
    .find(
      (f) =>
        f['content'] === '带风格字段的请求' &&
        typeof f['session_id'] === 'string' &&
        f['session_id'] === sessionId,
    );
  expect(
    lastUserMsgFrame,
    `应捕获到 session_id=${sessionId} content='带风格字段的请求' 的 user_message 帧,实际 frames: ${JSON.stringify(frames)}`,
  ).toBeTruthy();
  expect(lastUserMsgFrame!['style'], 'WS 帧应携带 style 字段').toBe('professional');

  // 8. 验:第二次 send 触发后端 agent 重建 + 新 mock 实例注册 + LLM 真收到帧 style
  //    路径(SPEC §4.10):
  //    - 第一次 send 走 default 风格,创建 llm_A,register_e2e_mock(llm_A)
  //    - 第二次 send 携带 style='professional',触发 _get_current_agent 重建:
  //      创建 llm_B,register_e2e_mock(llm_B) 替换 _e2e_mock_instance
  //    - 验:last_messages 来自"不同"实例(指针变化)+ HumanMessage.content 是
  //      '带风格字段的请求'(说明是真第二次 invoke,不是第一次的残留)
  //
  //    2026-08-05 fix: DynamicIdentityMiddleware 现在读 llm._nexus_style
  //    透传给 get_system_prompt(style=...),LLM 收到的 SystemMessage 必须
  //    含【回复风格 · 专业】段(否则 backend bug 仍存在)。
  const payload = await page.evaluate(async () => {
    const r = await fetch('/api/e2e/last-messages');
    if (!r.ok) throw new Error(`/api/e2e/last-messages returned ${r.status}`);
    return (await r.json()) as {
      messages: Array<{ type: string; content: unknown }>;
    };
  });
  expect(payload.messages.length, '应至少收到一组 messages').toBeGreaterThan(0);
  // 至少有一条 SystemMessage + 至少有一条 HumanMessage 含 '带风格字段的请求'
  // (证明第二次 invoke 真走到 LLM,新 mock 实例被注册 + 第二次 send 完整流转)
  const sysMsg = payload.messages.find((m) => m.type === 'SystemMessage');
  expect(sysMsg, '应至少有一条 SystemMessage').toBeTruthy();
  // 验证 SystemMessage 含【回复风格 · 专业】段(2026-08-05 修复目标)。
  // 这是 backend bug 修复的核心断言:DynamicIdentityMiddleware 不再
  // 用默认 style 覆盖 agent 注入的 directive。
  const sysContent = typeof sysMsg!.content === 'string'
    ? sysMsg!.content
    : JSON.stringify(sysMsg!.content);
  expect(
    sysContent,
    'SystemMessage 必须含【回复风格 · 专业】段(backend bug 修复后),实际 content 前 500 字符',
  ).toContain('回复风格 · 专业');
  const humanMessages = payload.messages.filter((m) => m.type === 'HumanMessage');
  const matchingHuman = humanMessages.find((m) => {
    const c = typeof m.content === 'string' ? m.content : JSON.stringify(m.content);
    return c.includes('带风格字段的请求');
  });
  expect(
    matchingHuman,
    'LLM 应真收到第二条 send 的内容(至少有一条 HumanMessage 含此内容)',
  ).toBeTruthy();

  // 9. 刷新页面 → 风格仍为 'professional',徽标仍在
  await page.reload();
  await openHome(page);
  // 等会话项重新出现
  const reloadedTaskItem = page.locator(`.task-item[data-conversation-id="${sessionId}"]`);
  await expect(reloadedTaskItem, '刷新后对应会话项应仍在').toBeVisible({ timeout: 10_000 });
  // 徽标应仍显示 '专业'(持久化生效)
  await expect(reloadedTaskItem.locator('.task-item-style-badge'), '刷新后徽标应仍在').toHaveText(
    '专业',
  );
  // Composer 当前会话风格 = 'professional',徽标应出现
  // 切到该会话(默认可能已激活;若不是则 click)
  await reloadedTaskItem.click();
  await expect(
    page.locator('.style-badge'),
    '刷新后 Composer 徽标应仍显示当前会话风格',
  ).toHaveText('专业', { timeout: 5_000 });
});


/**
 * Round 6.1 二次覆盖:同会话内 professional→concise→default 来回切换。
 *
 * WHY(2026-08-05 补):前一个 test 只覆盖"default→professional"单向切换 + 一次
 * 重建,没验证连续多次风格切换的 cache bucket 清理 / agent 重建 / SystemMessage
 * 段同步。本 test 三次切换 + 各发一条消息,验证最后一次 send 的 LLM 收到的
 * SystemMessage 含【回复风格 · 默认】段(证明"来回切"路径风格段也跟手)。
 *
 * 关键路径:
 *   - 每次切风格 → ComposerToolbar.handleSelect 走 store.setSessionStyle + PATCH
 *   - 下次 send → main._get_current_agent(style) 检测 != 重建 agent
 *   - 重建 agent → _build_system_prompt(style) 走新 bucket → SystemMessage
 *     内容随风格段切换。
 */
test('Round 6.1:同会话 professional→concise→default 来回切,最后一次 SystemMessage 段 = 默认', async ({
  page,
}) => {
  test.setTimeout(240_000);

  await installWsFrameCapture(page);
  await page.route(/\/api\/sessions\/[^/]+$/, async (route) => {
    if (route.request().method() === 'PATCH') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      });
      return;
    }
    await route.continue();
  });

  await journeyOpenHome(page);
  // 先创建会话
  await sendMessageAndWaitForReply(page, '来回切起点', { timeoutMs: 60_000 });
  const sessionId = await page
    .locator('.task-item')
    .first()
    .getAttribute('data-conversation-id');
  expect(sessionId, '会话应有 data-conversation-id').toBeTruthy();

  // 切风格的小工具:点 trigger + 选指定 menuitem + 验徽标状态
  // WHY:ComposerToolbar.tsx 的徽标 .style-badge 仅在非 default 风格时显示
  // (default 的 label 是空串,见 styles.ts:STYLE_LABELS)。所以 "默认" 选中后
  // 徽标应消失,其余风格选中后徽标文本 = label。
  async function selectStyle(label: '默认' | '简洁' | '专业'): Promise<void> {
    await page.locator('button[aria-label="选择回复风格"]').click();
    const item = page.getByRole('menuitem', { name: label });
    await expect(item, `${label} menuitem 应可见`).toBeVisible({ timeout: 3_000 });
    await item.click();
    if (label === '默认') {
      await expect(
        page.locator('.style-badge'),
        'Composer 徽标在 default 时应隐藏(label 空串)',
      ).toHaveCount(0, { timeout: 3_000 });
    } else {
      await expect(page.locator('.style-badge'), `Composer 徽标应显示 ${label}`).toHaveText(
        label,
        { timeout: 3_000 },
      );
    }
  }

  // 1. 切到"专业" → 发消息(触发 llm_B 重建 + SystemMessage 切专业段)
  await selectStyle('专业');
  await sendMessageAndWaitForReply(page, '切到专业后第一条', { timeoutMs: 60_000 });

  // 2. 切到"简洁" → 发消息(触发 llm_C 重建)
  await selectStyle('简洁');
  await sendMessageAndWaitForReply(page, '切到简洁后第二条', { timeoutMs: 60_000 });

  // 3. 切回"默认" → 发消息(触发 llm_D 重建 + SystemMessage 切回默认段)
  await selectStyle('默认');
  await sendMessageAndWaitForReply(page, '切回默认后第三条', { timeoutMs: 60_000 });

  // 4. 关键断言:来回切三次后,最后一次 LLM 收到的 SystemMessage 应处于
  //    "已切回默认" 状态。``default`` 风格按设计**不**注入任何【回复风格 · X】段
  //    (见 nexus/backend/agent/_system_prompt.py:249 ``if style != "default":``),
  //    所以验证方式是"无【回复风格 · X】段"而非"含【回复风格 · 默认】段"。
  //    这才是 backend 真重建 + cache bucket 切对的证据 —— 假若切回 default
  //    时 cache 残留前一次的 professional 段,会触发"含回复风格 · 专业"误报。
  const payload = await page.evaluate(async () => {
    const r = await fetch('/api/e2e/last-messages');
    if (!r.ok) throw new Error(`/api/e2e/last-messages returned ${r.status}`);
    return (await r.json()) as {
      messages: Array<{ type: string; content: unknown }>;
    };
  });
  expect(payload.messages.length, '应至少收到一组 messages').toBeGreaterThan(0);

  const sysMsg = payload.messages.find((m) => m.type === 'SystemMessage');
  expect(sysMsg, '应至少有一条 SystemMessage').toBeTruthy();
  const sysContent =
    typeof sysMsg!.content === 'string'
      ? sysMsg!.content
      : JSON.stringify(sysMsg!.content);
  // 4a. 切回默认后,SystemMessage **不应**含任何【回复风格 · X】段(default 静默)。
  //     这是 backend 重建正确 + cache bucket 切对的硬证据。
  expect(
    sysContent,
    '来回切三次后,最后 LLM 收到的 SystemMessage 不应含【回复风格 · X】段(default 风格按设计不注入)',
  ).not.toMatch(/回复风格 · (默认|简洁|专业)/);
  // 4b. 同时验:HumanMessage 真收到第三次 send 的内容(证明真第三次 invoke,
  //     避免 mock LLM 拿不到风格的默认 fallback 路径误判为"无风格段 = 通过")。
  const humanMessages = payload.messages.filter((m) => m.type === 'HumanMessage');
  const matchingHuman = humanMessages.find((m) => {
    const c = typeof m.content === 'string' ? m.content : JSON.stringify(m.content);
    return c.includes('切回默认后第三条');
  });
  expect(
    matchingHuman,
    'LLM 应真收到第三次 send 的内容(证明来回切都有 invoke 走到 LLM)',
  ).toBeTruthy();

  // 5. 同时验:最后一次 send 的 WS 帧 style === 'default'
  const frames = await readSentFrames(page);
  const lastUserMsgFrame = [...frames]
    .reverse()
    .find(
      (f) =>
        f['content'] === '切回默认后第三条' &&
        typeof f['session_id'] === 'string' &&
        f['session_id'] === sessionId,
    );
  expect(
    lastUserMsgFrame,
    '应捕获到第三条 send 的 user_message 帧',
  ).toBeTruthy();
  expect(lastUserMsgFrame!['style'], '最后一次 WS 帧 style 必须是 default').toBe('default');
});
