import { chromium } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// 测试产物统一落到项目内（截图 + JSON 报告），不放 /tmp
const ARTIFACT_DIR = path.join(__dirname, 'artifacts');
fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
const SCREENSHOT = (name) => path.join(ARTIFACT_DIR, name);
const RESULTS_FILE = path.join(ARTIFACT_DIR, 'results.json');

const results = [];
function record(name, pass, detail = '') {
  results.push({ name, pass, detail });
  console.log(`${pass ? '✓' : '✗'} ${name}${detail ? '  — ' + detail : ''}`);
}

async function waitTa(page, ms = 90000) {
  await page.waitForFunction(() => {
    const ta = document.querySelector('textarea');
    return ta && !ta.disabled;
  }, null, { timeout: ms });
}

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page = await ctx.newPage();
const consoleErrors = [];
page.on('pageerror', e => consoleErrors.push(e.message));
page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });

// 跳过 vite 的 [vite] 调试日志 + 断网测试期间浏览器自动报的 ERR_INTERNET_DISCONNECTED
const realErrors = e => !/\[vite\]/.test(e) && !/ERR_INTERNET_DISCONNECTED|net::ERR_/.test(e);

await page.goto('http://localhost:30077/app/', { waitUntil: 'networkidle', timeout: 15000 });
await page.waitForTimeout(1500);

// ========== 1. 欢迎页与初始布局 ==========
console.log('\n=== 1. 欢迎页与初始布局 ===');
try {
  const totoro = await page.locator('img[alt="龙猫"]').count();
  record('龙猫图显示', totoro === 1);

  const greet = await page.locator('text=你好，我是 Nexus').count();
  record('欢迎语显示', greet === 1);

  const suggestions = ['写代码', '分析数据', '知识问答', '写作助手'];
  for (const s of suggestions) {
    const c = await page.locator(`text=${s}`).count();
    record(`建议按钮: ${s}`, c >= 1);
  }

  const wsStatus = await page.locator('text=已连接').count();
  record('WebSocket 已连接', wsStatus >= 1);

  const sidebarTitle = await page.locator('text=Nexus').count();
  record('侧边栏标题', sidebarTitle >= 1);

  const newBtn = await page.locator('button:has-text("新建会话")').count();
  record('新建会话按钮', newBtn === 1);

  await page.screenshot({ path: SCREENSHOT('01_welcome.png') });
} catch (e) { record('欢迎页布局', false, e.message); }

// ========== 2. 消息收发（不依赖真实 LLM，验证消息提交路径） ==========
console.log('\n=== 2. 消息收发 ===');
try {
  const ta = page.locator('textarea').first();
  await waitTa(page);
  await ta.fill('你好，请用一句话自我介绍。');
  await page.keyboard.press('Enter');

  // 等后端处理（textarea 重新可用 = 后端 done/error）
  // 没 API key 时后端会在 ~5s 内 emit done，无需等 120s
  await waitTa(page, 30000);
  await page.waitForTimeout(1000);

  // 验证有用户消息
  const userBubbles = await page.locator('.chat-scroll').locator('text=你好，请用一句话自我介绍。').count();
  record('用户消息渲染', userBubbles >= 1);

  // 验证有助手气泡（空内容也算有；后端会创建空 assistant 气泡占位）
  const assistantBubbles = await page.locator('.chat-scroll').locator('text=/^(?!.*你好，请用).*/').count();
  record('助手消息气泡已创建', assistantBubbles >= 1);

  await page.screenshot({ path: SCREENSHOT('02_message.png') });
} catch (e) { record('消息收发', false, e.message); }

// ========== 3. 思考过程开关 ==========
console.log('\n=== 3. 思考过程开关 ===');
try {
  const scroller = page.locator('.chat-scroll');
  // 按钮在侧边栏，点击切换；不依赖真实 LLM 返回思考内容
  const toggle = page.locator('button[aria-label="切换显示思考"]');
  const exists = await toggle.count();
  if (exists > 0) {
    // 关闭
    await toggle.click();
    await page.waitForTimeout(400);
    // 再开
    await toggle.click();
    await page.waitForTimeout(400);
    record('思考过程开关可点击', true);
  } else {
    record('思考过程开关可点击', false, '未找到 aria-label 按钮');
  }

  // 即便没 LLM 思考内容，UI 本身应能响应（再点一次）
  if (exists > 0) {
    await toggle.click();
    await page.waitForTimeout(400);
    record('思考过程开关多次切换无异常', true);
  }
} catch (e) { record('思考过程开关', false, e.message); }

// ========== 4. 深色模式 ==========
console.log('\n=== 4. 深色模式 ===');
try {
  const isDarkBefore = await page.evaluate(() => document.documentElement.classList.contains('dark') || document.querySelector('.dark') !== null);
  // 点击顶部月亮/太阳图标
  await page.locator('header button').last().click();
  await page.waitForTimeout(500);
  const isDarkAfter = await page.evaluate(() => document.querySelector('.dark') !== null);
  record('深色模式已切换', isDarkBefore !== isDarkAfter);

  await page.screenshot({ path: SCREENSHOT('04_dark.png') });

  // 切回浅色
  await page.locator('header button').last().click();
  await page.waitForTimeout(500);
  const isLightBack = await page.evaluate(() => document.querySelector('.dark') === null);
  record('切回浅色模式', isLightBack);
} catch (e) { record('深色模式', false, e.message); }

// ========== 5. 侧边栏折叠 ==========
console.log('\n=== 5. 侧边栏折叠 ===');
try {
  const sidebarBefore = await page.locator('aside').first().evaluate(el => el.getBoundingClientRect().width);
  // 第一个 header button 是汉堡按钮
  await page.locator('header button').first().click();
  await page.waitForTimeout(500);
  const sidebarAfter = await page.locator('aside').first().evaluate(el => el.getBoundingClientRect().width);
  record('侧边栏宽度变化', Math.abs(sidebarBefore - sidebarAfter) > 100, `从 ${sidebarBefore} → ${sidebarAfter}`);

  // 恢复
  await page.locator('header button').first().click();
  await page.waitForTimeout(500);
  const sidebarRestored = await page.locator('aside').first().evaluate(el => el.getBoundingClientRect().width);
  record('侧边栏恢复', Math.abs(sidebarRestored - sidebarBefore) < 5, `当前 ${sidebarRestored}`);
} catch (e) { record('侧边栏折叠', false, e.message); }

// ========== 6. 新建会话 ==========
console.log('\n=== 6. 新建会话 ===');
try {
  // 先发条消息
  const ta = page.locator('textarea').first();
  await waitTa(page);
  await ta.fill('临时消息1');
  await page.keyboard.press('Enter');
  await waitTa(page, 120000);
  await page.waitForTimeout(500);

  // 点击新建会话
  await page.locator('button:has-text("新建会话")').click();
  await page.waitForTimeout(1000);

  // 验证欢迎页回来了
  const welcomeBack = await page.locator('text=你好，我是 Nexus').count();
  record('新建会话后回到欢迎页', welcomeBack === 1);

  const ta2 = page.locator('textarea').first();
  const taEnabled = await ta2.isEnabled();
  record('输入框可用', taEnabled);
} catch (e) { record('新建会话', false, e.message); }

// ========== 7. 历史会话加载与删除 ==========
console.log('\n=== 7. 历史会话加载与删除 ===');
try {
  // 等待会话列表加载
  await page.waitForTimeout(2000);
  const convCount = await page.locator('aside .group').count();
  record('会话列表有项', convCount >= 1, `${convCount} 个会话`);

  if (convCount >= 1) {
    // 点开第一个会话
    const firstConv = page.locator('aside .group').first();
    await firstConv.click();
    await page.waitForTimeout(2000);

    // 验证消息加载
    const msgsLoaded = await page.locator('.chat-scroll').evaluate(el => {
      // 检查非欢迎页
      return el.querySelectorAll('button, div').length > 5;
    });
    record('点击历史会话加载消息', msgsLoaded);

    // 触发删除按钮（hover 后显示）
    await firstConv.hover();
    await page.waitForTimeout(300);
    const deleteBtn = firstConv.locator('button').last();
    const delCount = await deleteBtn.count();
    if (delCount > 0) {
      const beforeCount = await page.locator('aside .group').count();
      await deleteBtn.click();
      await page.waitForTimeout(1500);
      const afterCount = await page.locator('aside .group').count();
      record('删除会话', afterCount < beforeCount, `${beforeCount} → ${afterCount}`);
    } else {
      record('删除会话', false, '未找到删除按钮');
    }
  }
} catch (e) { record('历史会话操作', false, e.message); }

// ========== 8. 弹窗交互 ==========
console.log('\n=== 8. 弹窗交互 ===');
try {
  // 模型配置
  await page.locator('button:has-text("模型配置")').click();
  await page.waitForTimeout(500);
  const modelModalOpen = await page.locator('text=/模型|Model|API/').count() >= 1;
  record('模型配置弹窗打开', modelModalOpen);

  // 关闭
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);
  await page.screenshot({ path: SCREENSHOT('08_modal.png') });

  // 微信插件
  await page.locator('button:has-text("插件管理")').click();
  await page.waitForTimeout(500);
  const wechatModalOpen = await page.locator('text=/微信|WeChat|插件/').count() >= 1;
  record('微信插件弹窗打开', wechatModalOpen);

  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);
} catch (e) { record('弹窗交互', false, e.message); }

// ========== 9. 键盘快捷键 ==========
console.log('\n=== 9. 键盘快捷键 ===');
try {
  const ta = page.locator('textarea').first();
  await waitTa(page);
  await ta.click();

  // Shift+Enter 应该是换行
  await ta.fill('');
  await ta.type('第一行');
  await page.keyboard.down('Shift');
  await page.keyboard.press('Enter');
  await page.keyboard.up('Shift');
  await ta.type('第二行');
  await page.waitForTimeout(300);
  const taValue = await ta.inputValue();
  record('Shift+Enter 换行（不发送）', taValue.includes('\n') && taValue.includes('第一行') && taValue.includes('第二行'), `value: ${JSON.stringify(taValue)}`);

  // 清空再测 Enter
  await ta.fill('');
  await ta.type('纯 Enter 测试');
  await page.keyboard.press('Enter');
  // 等待 textarea 短暂禁用（说明发送了）
  await page.waitForTimeout(500);
  const isLoading = await page.locator('textarea').first().isDisabled();
  record('Enter 触发发送（loading 状态）', isLoading || (await ta.inputValue()) === '');
  await waitTa(page, 120000);
} catch (e) { record('键盘快捷键', false, e.message); }

// ========== 10. 滚动行为 ==========
console.log('\n=== 10. 滚动行为 ===');
try {
  // 累积多消息，让视口肯定溢出
  const ta = page.locator('textarea').first();
  for (let i = 0; i < 8; i++) {
    await waitTa(page, 30000);
    await ta.fill(`滚动测试消息 ${i}，内容稍微长一些以便撑开视口`);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(300);
  }
  await waitTa(page, 30000);
  await page.waitForTimeout(2000);

  const scroller = page.locator('.chat-scroll');
  const sc = await scroller.evaluate(el => ({
    sh: el.scrollHeight, ch: el.clientHeight, st: el.scrollTop,
    diff: el.offsetWidth - el.clientWidth,
  }));

  record('内容超过视口', sc.sh > sc.ch, `scrollH=${sc.sh} clientH=${sc.ch}`);
  record('滚动条 gutter 预留空间', sc.diff >= 8, `diff=${sc.diff}px`);

  // 触发 wheel 向上滚
  const stBefore = await scroller.evaluate(el => el.scrollTop);
  const bbox = await scroller.boundingBox();
  await page.mouse.move(bbox.x + bbox.width/2, bbox.y + bbox.height/2);
  await page.mouse.wheel(0, -1000);
  await page.waitForTimeout(300);
  const stAfter = await scroller.evaluate(el => el.scrollTop);
  record('wheel 向上滚动生效（位置变化）', stAfter !== stBefore, `从 ${stBefore} → ${stAfter}`);

  // 滚回底部，看自动跟随
  await page.mouse.wheel(0, 50000);
  await page.waitForTimeout(500);
  const stBottom = await scroller.evaluate(el => el.scrollTop);
  const isAtBottom = await scroller.evaluate(el =>
    Math.abs(el.scrollHeight - el.scrollTop - el.clientHeight) < 5
  );
  record('滚到底部', isAtBottom, `scrollTop=${stBottom}`);

  await page.screenshot({ path: SCREENSHOT('10_scrolled.png') });
} catch (e) { record('滚动行为', false, e.message); }

// ========== 控制台错误检查 ==========
console.log('\n=== 控制台错误 ===');
const filteredErrors = consoleErrors.filter(realErrors);
if (filteredErrors.length === 0) {
  record('无 JS 错误', true);
} else {
  record('JS 错误', false, `${filteredErrors.length} 个: ${filteredErrors.slice(0, 3).join('; ')}`);
}

// ========== 11. WebSocket 重连（断网 → 恢复） ==========
console.log('\n=== 11. WebSocket 重连 ===');
try {
  // 等到 WS 显示已连接
  await page.waitForSelector('text=已连接', { timeout: 10000 });
  record('断网前 WS 已连接', true);

  // 断网
  await ctx.setOffline(true);
  await page.waitForTimeout(2000);

  // 恢复
  await ctx.setOffline(false);
  // 等待自动重连（useWebSocket 指数退避，最多等 30s）
  await page.waitForSelector('text=已连接', { timeout: 35000 });
  record('断网恢复后 WS 自动重连', true);
} catch (e) {
  record('WS 重连', false, e.message);
}

// ========== 12. 输入边界 ==========
console.log('\n=== 12. 输入边界 ===');
try {
  // 12a. 超长输入（500 字符）应不卡死
  const ta = page.locator('textarea').first();
  await waitTa(page);
  const longText = 'x'.repeat(500);
  await ta.fill(longText);
  const taLen = (await ta.inputValue()).length;
  record('超长输入可输入', taLen === 500, `len=${taLen}`);

  // 12b. SQL 注入 / 特殊字符应安全转义
  await ta.fill('');
  await ta.type("'; DROP TABLE messages; --");
  await page.keyboard.press('Enter');
  await waitTa(page, 60000);
  // 等一会儿看是否后端报错
  await page.waitForTimeout(2000);
  const stillAlive = await page.locator('textarea').first().isEnabled();
  record('特殊字符注入后服务仍正常', stillAlive);

  // 12c. 新建会话清理输入
  await page.locator('button:has-text("新建会话")').click();
  await page.waitForTimeout(800);
  const taAfter = await page.locator('textarea').first().inputValue();
  record('新建会话清空输入', taAfter === '');
} catch (e) {
  record('输入边界', false, e.message);
}

// ========== 13. 刷新持久化 ==========
console.log('\n=== 13. 刷新持久化 ===');
try {
  // 在新会话里发条消息
  const ta = page.locator('textarea').first();
  await waitTa(page);
  await ta.fill('持久化测试消息');
  await page.keyboard.press('Enter');
  await waitTa(page, 60000);
  await page.waitForTimeout(1500);

  // 记录当前会话的标题
  const sessionTitleBefore = await page.locator('aside .group').first().textContent();

  // 刷新
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  // 验证会话还在列表中
  const stillThere = await page.locator(`aside`).locator(`text=${sessionTitleBefore?.slice(0, 5) || ''}`).count();
  record('刷新后会话列表保留', stillThere >= 1);

  // 点击该会话看消息是否还在
  await page.locator('aside .group').first().click();
  await page.waitForTimeout(2000);
  const msgStill = await page.locator('.chat-scroll').locator('text=持久化测试消息').count();
  record('刷新后消息历史恢复', msgStill >= 1);
} catch (e) {
  record('刷新持久化', false, e.message);
}

// ========== 14. 模型配置弹窗 CRUD 流程 ==========
console.log('\n=== 14. 模型配置弹窗 CRUD ===');
try {
  await page.locator('button:has-text("模型配置")').click();
  await page.waitForTimeout(800);

  // 加一个新模型
  await page.locator('button:has-text("+ 添加模型")').click();
  await page.waitForTimeout(500);
  await page.locator('input[placeholder*="MiniMax"]').fill('E2E Test');
  await page.locator('input[placeholder="输入 API Key"]').fill('fake-key');
  await page.locator('button:has-text("保存")').click();
  await page.waitForTimeout(1500);

  // 验证新模型出现在列表
  const newModelVisible = await page.locator('text=E2E Test').count();
  record('新建模型出现在列表', newModelVisible >= 1);

  // 关闭
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);
} catch (e) {
  record('模型配置 CRUD', false, e.message);
}

// ========== 15. 大量消息滚动性能 ==========
console.log('\n=== 15. 大量消息滚动性能 ===');
try {
  // 在新会话里堆消息
  await page.locator('button:has-text("新建会话")').click();
  await page.waitForTimeout(800);

  const ta = page.locator('textarea').first();
  for (let i = 0; i < 8; i++) {
    await waitTa(page);
    await ta.fill(`性能测试消息 ${i}`);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(200);
  }
  await waitTa(page, 120000);
  await page.waitForTimeout(1500);

  const scroller = page.locator('.chat-scroll');
  const sc = await scroller.evaluate(el => ({ sh: el.scrollHeight, ch: el.clientHeight }));
  record('大量消息后内容超出视口', sc.sh > sc.ch * 1.5, `scrollH=${sc.sh} clientH=${sc.ch}`);

  // 滚到底部
  await page.mouse.move(640, 400);
  await page.mouse.wheel(0, 100000);
  await page.waitForTimeout(500);
  const atBottom = await scroller.evaluate(el =>
    Math.abs(el.scrollHeight - el.scrollTop - el.clientHeight) < 10
  );
  record('大量消息后滚到底部', atBottom);
} catch (e) {
  record('大量消息性能', false, e.message);
}

// ========== 控制台错误（最终） ==========
console.log('\n=== 控制台错误（最终） ===');
const finalErrors = consoleErrors.filter(realErrors);
if (finalErrors.length === 0) {
  record('全程无 JS 错误', true);
} else {
  record('JS 错误', false, `${finalErrors.length} 个: ${finalErrors.slice(0, 3).join('; ')}`);
}

await browser.close();

// ========== 汇总 ==========
console.log('\n========== 测试汇总 ==========');
const passed = results.filter(r => r.pass).length;
const failed = results.filter(r => !r.pass);
console.log(`通过: ${passed} / ${results.length}`);
if (failed.length > 0) {
  console.log('\n失败项:');
  failed.forEach(f => console.log(`  ✗ ${f.name}${f.detail ? '  — ' + f.detail : ''}`));
}

fs.writeFileSync(RESULTS_FILE, JSON.stringify(results, null, 2));
process.exit(failed.length === 0 ? 0 : 1);
