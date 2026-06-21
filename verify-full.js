const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:30077';
// 截图落项目内目录(.verify-shots/),对齐 .gitignore 与项目测试产物规则。
const SHOT_DIR = path.join(__dirname, '.verify-shots');
if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });

const log = (...args) => console.log('[verify]', ...args);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function shot(page, name) {
  await page.screenshot({ path: `${SHOT_DIR}/${name}.png`, fullPage: true });
  log('📸', name);
}

async function dump(page, label) {
  const data = await page.evaluate(() => {
    const userRows = document.querySelectorAll('.message-row.is-user').length;
    const asstRows = document.querySelectorAll('.message-row.is-assistant').length;
    const taskItems = Array.from(document.querySelectorAll('.task-item')).map((el) => {
      const strong = el.querySelector('strong');
      const active = el.classList.contains('is-current');
      return { title: strong?.innerText || '', active };
    });
    return {
      url: location.href,
      view: location.pathname + (location.hash || ''),
      pill: document.querySelector('[role="status"]')?.innerText || null,
      emptyHero: !!document.querySelector('.empty-state'),
      messageListVisible: !!document.querySelector('.message-list'),
      userRows, asstRows,
      taskItems,
    };
  });
  log(label, JSON.stringify(data, null, 2));
  return data;
}

async function waitReady(page) {
  // 等"本地运行已就绪"(SetupView) 或 pill(ChatView) 任一出现
  await Promise.race([
    page.waitForFunction(() => document.body.innerText.includes('本地运行已就绪'), { timeout: 25_000 }),
    page.waitForSelector('[role="status"]', { timeout: 25_000 }),
  ]).catch(() => {});
  await sleep(500);
}

async function newTask(page) {
  // 优先 sidebar "新任务" 按钮
  const btn = await page.$('button.btn-new-task');
  if (btn) {
    await btn.click();
    log('clicked sidebar 新任务');
  } else {
    // 欢迎页 CTA
    const cta = await page.$('button:has-text("+ 新建第一个任务")') || await page.$('button[class*="hero-cta"]');
    if (cta) {
      await cta.click();
      log('clicked 欢迎页 CTA');
    } else {
      throw new Error('no entry point to ChatView');
    }
  }
  await waitReady(page);
}

async function sendMsg(page, content, timeoutMs = 90_000) {
  const before = await page.evaluate(() => ({
    user: document.querySelectorAll('.message-row.is-user').length,
    asst: document.querySelectorAll('.message-row.is-assistant').length,
  }));

  const ta = await page.waitForSelector('textarea', { timeout: 10_000 });
  await ta.click({ clickCount: 3 });
  await page.keyboard.press('Backspace');
  await ta.type(content);
  await page.click('button[aria-label="发送消息"]');
  log('sent:', content.slice(0, 40));

  // 等 user +1,新 assistant row 出现,最后一 assistant <p> 文本非空,
  // 且不是 user 行数对齐
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const state = await page.evaluate((b) => {
      const userRows = document.querySelectorAll('.message-row.is-user p');
      const asstRows = document.querySelectorAll('.message-row.is-assistant p');
      const last = asstRows[asstRows.length - 1];
      return {
        user: userRows.length,
        asst: asstRows.length,
        userDelta: userRows.length - b.user,
        asstDelta: asstRows.length - b.asst,
        lastText: (last?.innerText || '').trim(),
      };
    }, before);
    // 必须:user 已 +1,asst 已 >= +1(loading 占位也算 1),最后一 asst 有非空文本,
    // 且 user/asst 行数对齐
    if (
      state.userDelta >= 1 &&
      state.asstDelta >= 1 &&
      state.asst >= state.user &&
      state.lastText.length > 0
    ) {
      log(`  assistant replied: user+${state.userDelta} asst+${state.asstDelta} (${state.lastText.length} chars) in ${Date.now() - start}ms`);
      return state.lastText;
    }
    await sleep(500);
  }
  throw new Error('timeout waiting for assistant reply');
}

async function clickSidebarTask(page, title) {
  // 准确点 .task-item,匹配 strong 文本
  const handle = await page.evaluateHandle((t) => {
    const items = Array.from(document.querySelectorAll('.task-item'));
    return items.find((el) => el.querySelector('strong')?.innerText === t) || null;
  }, title);
  const el = handle.asElement();
  if (!el) throw new Error(`sidebar task not found: ${title}`);
  await el.click();
  log('clicked sidebar task:', title);
  await sleep(1200);  // 给 onSelectConversation + fetch + render 时间
}

(async () => {
  const browser = await puppeteer.launch({
    headless: 'new',
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });
  const page = await browser.newPage();
  page.setDefaultTimeout(20_000);
  await page.setViewport({ width: 1320, height: 860 });

  // capture console
  page.on('console', (msg) => {
    const t = msg.type();
    if (t === 'error' || t === 'warning') console.log(`[browser:${t}]`, msg.text().slice(0, 200));
  });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message.slice(0, 200)));

  try {
    log('=== STEP 1: load page ===');
    await page.goto(`${BASE}/app/`, { waitUntil: 'networkidle2' });
    await waitReady(page);
    await shot(page, '01-initial');
    await dump(page, '1.initial:');

    log('=== STEP 2: 新建第一个任务 ===');
    await newTask(page);
    await shot(page, '02-new-task');
    await dump(page, '2.after-new-task:');

    log('=== STEP 3: 发第一条消息 ===');
    const reply1 = await sendMsg(page, '你好，自我介绍下,1 句话就行。', 60_000);
    log('reply1:', reply1.slice(0, 80));
    await shot(page, '03-first-reply');

    log('=== STEP 4: 多轮对话 ===');
    const reply2 = await sendMsg(page, '你叫什么名字?');
    log('reply2:', reply2.slice(0, 80));
    const reply3 = await sendMsg(page, '记住这个项目叫 "Nexus DMG 验收"。');
    log('reply3:', reply3.slice(0, 80));
    await shot(page, '04-three-turns');

    log('=== STEP 5: 列表里出现 "Nexus DMG 验收" 任务吗? ===');
    const sidebarState = await dump(page, '5.sidebar-after-3-turns:');
    log('sidebar tasks:', sidebarState.taskItems);

    log('=== STEP 6: 切换到另一个任务(点 sidebar "新任务"),原任务记录不丢 ===');
    await newTask(page);
    await shot(page, '06-second-new-task');
    // 在新任务里发一条
    const reply4 = await sendMsg(page, '这是第二个任务,记一下我今天喝了三杯咖啡。', 120_000);
    log('reply4:', reply4.slice(0, 80));
    await shot(page, '07-second-task-msg');
    await dump(page, '7.second-task-state:');

    log('=== STEP 7: 切回第一个任务,记录还在吗? ===');
    // 取第一个任务的真实 title(从 taskItems 选)
    const firstTask = sidebarState.taskItems.find((t) => t.title && t.title.length > 0);
    log('switching back to:', JSON.stringify(firstTask));
    if (firstTask && firstTask.title) {
      await clickSidebarTask(page, firstTask.title);
      await shot(page, '08-back-to-first');
      const firstTaskState = await dump(page, '8.first-task-after-switch:');
      log('  active task items:', firstTaskState.taskItems);
      // 关键断言:第一条 user 消息 "你好" 还在
      const firstUserText = await page.evaluate(() => {
        const row = document.querySelector('.message-row.is-user p');
        return row?.innerText || null;
      });
      log('CRITICAL first user message after switch:', JSON.stringify(firstUserText?.slice(0, 60)));
      if (!firstUserText || !firstUserText.includes('你好')) {
        log('❌ BUG: 切回第一个任务,user 消息没显示');
      } else {
        log('✅ 切回第一个任务,user 消息正常显示');
      }
    } else {
      log('⚠️ 没找到第一个任务,跳过 step 7');
    }

    log('=== STEP 8: 刷新页面,session 持久化吗? ===');
    await page.reload({ waitUntil: 'networkidle2' });
    await waitReady(page);
    await sleep(1500);
    await shot(page, '09-after-reload');
    const reloadState = await dump(page, '9.after-reload:');
    log('✅ reload 任务列表:', reloadState.sidebarTasks);

    log('=== STEP 9: 设置 / 微信 modal ===');
    // 用 .footer-link 文字匹配
    const settingsHandle = await page.evaluateHandle(() => {
      return Array.from(document.querySelectorAll('button.footer-link')).find(
        (b) => b.innerText.includes('设置')
      ) || null;
    });
    const settings = settingsHandle.asElement();
    if (settings) {
      await settings.click();
      await sleep(500);
      await shot(page, '10-settings');
      log('settings opened');
    } else {
      log('⚠️ settings button not found');
    }

  } catch (err) {
    console.log('❌ ERROR:', err.message);
    console.log(err.stack);
  } finally {
    await browser.close();
    log('=== DONE ===');
  }
})();
