/**
 * User Journey: Round 5 T5.3 — PreferencesModal 的 Plugins tab 渲染验证。
 *
 * 用户故事:
 *   1. 打开主页(ChatView),mock LLM 链路初始化完成
 *   2. 点侧栏"设置"按钮 → PreferencesModal 打开,默认在"常规"tab
 *   3. 切到"Plugins" tab → PluginsPanel 渲染 mock fixture 中的所有字段
 *      (name / version / description / type / path)
 *
 * 关键决策(WHY):
 *   - NEXUS_E2E_MOCK=1:后端 mock LLM 是默认开关,沿用 round4 套件。
 *     但 mock 只替换 LLM,**不**保证 /api/plugins fixture 存在 — 实际后端
 *     会扫 ~/.nexus/plugins/ 真实目录(plugins_manifest 或类似),若目录
 *     不存在就返空数组(走 .plugins-panel-empty 路径),导致断言 fixture
 *     文本落空。
 *   - 解决方案:在 page.route() 拦截 /api/plugins,直接 fulfill 一份 2 条
 *     plugin 的稳定 fixture(weather / trans),与 vitest 单测同一组数据。
 *     这样不依赖后端状态,跨 spec 顺序跑稳。
 *   - 不拦 /api/* 其它端点:openHome 已 wait ChatView 渲染(说明 /api/models /
 *     /api/sessions /api/projects 等等链路都通过),没必要过度拦截。
 *
 * 触发器(读 Sidebar.tsx:240-252 / PreferencesModal.tsx:296-311):
 *   - "设置"按钮:aside.sidebar .sidebar-footer .settings-trigger,aria-label="设置"
 *   - "Plugins" tab:button[role="tab"]#preferences-tab-plugins,文本 "Plugins"
 *   - panel 容器:#preferences-tab-panel-plugins(role=tabpanel)
 *
 * 面板字段(PluginsPanel.tsx:54-70):
 *   - li.plugins-panel-item
 *   - .plugins-panel-name / .plugins-panel-version / .plugins-panel-type
 *   - .plugins-panel-description(仅当 description 非空)
 *   - .plugins-panel-path
 *
 * 运行:
 *   NEXUS_E2E_MOCK=1 npx playwright test \
 *     e2e/journey/journey-round5-plugins-tab.spec.ts
 */
import { test, expect } from '@playwright/test';
import { openHome } from '../helpers';

const MOCK = process.env.NEXUS_E2E_MOCK === '1';

test.skip(!MOCK, '本 spec 沿用 NEXUS_E2E_MOCK=1(plugins fixture 走 page.route 注入)');

// 与 vitest 单测 PluginsPanel.test.tsx:25-42 同款 fixture,字段稳定。
// 2 条 plugin:weather(type=tool,带 description)+ trans(type=hook,无 description),
// 验证 description 条件渲染分支。
const PLUGINS_FIXTURE = {
  plugins: [
    {
      name: 'weather',
      version: '1.2.3',
      description: '天气查询插件',
      type: 'tool',
      path: '/home/u/.nexus/plugins/weather',
    },
    {
      name: 'trans',
      version: '0.0.1',
      description: '',
      type: 'hook',
      path: '/home/u/.nexus/plugins/trans',
    },
  ],
};

test('Round 5 T5.3:Plugins tab 渲染 mock fixture 全部字段', async ({ page }) => {
  test.setTimeout(60_000);

  // 0. 拦截 /api/plugins → 稳定 fixture
  //    route 必须在 goto('/app/') 之前注册(避免 page hydration 后
  //    setOpen 时 react 触发 fetch 时漏过)。playwright 规则:goto 之前
  //    注册 route 覆盖该 host 的所有同 URL 请求,稳健。
  await page.route('**/api/plugins', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(PLUGINS_FIXTURE),
    });
  });

  // 1. 进 ChatView(modal 入口在 ChatView 的侧栏里)
  await openHome(page);

  // 2. 点侧栏"设置"按钮 → PreferencesModal 打开
  //    Sidebar.tsx:241-246 渲染 <button class="settings-trigger" aria-label="设置">。
  const settingsBtn = page.locator('aside.sidebar .sidebar-footer .settings-trigger');
  await expect(settingsBtn, '侧栏应渲染设置触发按钮').toBeVisible({ timeout: 5_000 });
  await settingsBtn.click();

  // 3. PreferencesModal 打开 + 默认切到 plugins tab
  //    PreferencesModal.tsx:528-542 渲染 #preferences-tab-panel-plugins。
  //    必须先切 tab,因为默认 activeTab='general'。
  const pluginsTab = page.locator('#preferences-tab-plugins');
  await expect(pluginsTab, 'Plugins tab 按钮应可见').toBeVisible({ timeout: 5_000 });
  await pluginsTab.click();

  // 4. PluginsPanel 渲染 — 等 2 条 .plugins-panel-item 出现
  const panel = page.locator('#preferences-tab-panel-plugins');
  await expect(panel, 'Plugins tabpanel 应可见').toBeVisible();
  const items = panel.locator('.plugins-panel-item');
  await expect(items, '应渲染 2 条 plugin(weather + trans)').toHaveCount(2, { timeout: 5_000 });

  // 5. 字段断言 — 与 PluginsPanel.test.tsx:47-57 对齐
  //    weather(name + version + description + type + path 都有)
  const firstItem = items.nth(0);
  await expect(firstItem.locator('.plugins-panel-name')).toHaveText('weather');
  await expect(firstItem.locator('.plugins-panel-version')).toHaveText('v1.2.3');
  await expect(firstItem.locator('.plugins-panel-description')).toHaveText('天气查询插件');
  await expect(firstItem.locator('.plugins-panel-type')).toHaveText('tool');
  await expect(firstItem.locator('.plugins-panel-path')).toHaveText(
    '/home/u/.nexus/plugins/weather',
  );

  //    trans(description 为空 → 不渲染 description 行)
  const secondItem = items.nth(1);
  await expect(secondItem.locator('.plugins-panel-name')).toHaveText('trans');
  await expect(secondItem.locator('.plugins-panel-version')).toHaveText('v0.0.1');
  await expect(secondItem.locator('.plugins-panel-type')).toHaveText('hook');
  await expect(secondItem.locator('.plugins-panel-path')).toHaveText(
    '/home/u/.nexus/plugins/trans',
  );
  await expect(secondItem.locator('.plugins-panel-description')).toHaveCount(0);
});
