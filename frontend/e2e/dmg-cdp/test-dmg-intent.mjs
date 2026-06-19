// E2E 验证意图识别端到端:
//   1) 发闲聊 → 后端落库 intent=chitchat
//   2) 发任务 → 后端落库 intent=task
//   3) sqlite3 直接查 messages 表确认 intent 列写入正确
//
// 前置:DMG 已启动并 NEXUS_DEVTOOLS=1,后端 30000,DevTools 9229。
// 跑法:node frontend/e2e/dmg-cdp/test-dmg-intent.mjs
import { execSync } from 'node:child_process';
import WebSocket from 'ws';
import { writeFileSync, mkdirSync } from 'node:fs';

const OUT = '/tmp/nexus-intent';
mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const target = JSON.parse(
  execSync('curl -s http://127.0.0.1:9229/json/list').toString()
).find((t) => t.url === 'http://127.0.0.1:30000/app/');

if (!target) {
  console.error('❌ 没找到 http://127.0.0.1:30000/app/ target,先 NEXUS_DEVTOOLS=1 open /Applications/Nexus.app');
  process.exit(1);
}

const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.on('open', r));

async function call(method, params = {}) {
  const id = Math.floor(Math.random() * 1e9);
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve) => {
    const h = (d) => {
      const m = JSON.parse(d);
      if (m.id === id) {
        ws.off('message', h);
        resolve(m.result);
      }
    };
    ws.on('message', h);
  });
}

async function ev(expr) {
  return (
    await call('Runtime.evaluate', {
      expression: expr,
      returnByValue: true,
      awaitPromise: true,
    })
  ).result.value;
}

console.log('reloading...');
await call('Page.reload', { ignoreCache: true });
await sleep(3500);

console.log('click new task...');
await ev(`document.querySelector('.btn-new-task')?.click()`);
await sleep(1500);

async function sendAndWait(question, maxWaitSec = 30) {
  await ev(
    `(() => { const ta = document.querySelector('.composer-textarea'); if (ta) { ta.focus(); ta.setSelectionRange(0, 0); } })()`
  );
  await sleep(200);
  // 用 native setter + InputEvent 触发 React onChange(CDP Input.insertText 不触发)
  await ev(
    `(() => { const ta = document.querySelector('.composer-textarea'); const proto = Object.getPrototypeOf(ta); const desc = Object.getOwnPropertyDescriptor(proto, 'value') || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value'); desc.set.call(ta, ${JSON.stringify(question)}); ta.dispatchEvent(new InputEvent('input', { bubbles: true, data: ${JSON.stringify(question)} })); })()`
  );
  await sleep(300);
  await call('Input.dispatchKeyEvent', {
    type: 'keyDown',
    key: 'Enter',
    code: 'Enter',
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  await call('Input.dispatchKeyEvent', {
    type: 'keyUp',
    key: 'Enter',
    code: 'Enter',
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  for (let i = 0; i < maxWaitSec; i++) {
    await sleep(1000);
    const len = await ev(
      `(() => { const arr = document.querySelectorAll('.message-row.is-assistant .message-bubble.message-assistant'); return arr.length > 0 ? arr[arr.length - 1].textContent.length : 0; })()`
    );
    const loading = await ev(
      `document.querySelectorAll('.loading-bubble').length`
    );
    if (len > 30 && loading === 0) return len;
  }
  return -1;
}

// 测 1:闲聊
console.log('sending chitchat...');
const chitchatLen = await sendAndWait('你好');
console.log(`[chitchat] asst-len=${chitchatLen}`);
await sleep(2000);

// 测 2:任务
console.log('sending task...');
const taskLen = await sendAndWait('请帮我把 1 到 10 的整数求和并解释算法');
console.log(`[task] asst-len=${taskLen}`);

// 截图
const scr = await call('Page.captureScreenshot', { format: 'png' });
writeFileSync(`${OUT}/intent-e2e.png`, Buffer.from(scr.data, 'base64'));

// 直接查 SQLite 验证 intent 列
let dbOut = '';
try {
  dbOut = execSync(
    `sqlite3 -separator '|' ~/.nexus/nexus.db "SELECT role, intent, substr(content, 1, 40) FROM messages WHERE content IN ('你好', '请帮我把 1 到 10 的整数求和并解释算法') ORDER BY created_at DESC LIMIT 4;"`
  ).toString();
} catch (e) {
  dbOut = `(sqlite3 query failed: ${e.message})`;
}
console.log('[db-tail]\n' + dbOut);

// 解析 db 输出,断言 intent 列
const dbLines = dbOut.split('\n').filter(Boolean);
const chitchatRow = dbLines.find((l) => l.includes('你好'));
const taskRow = dbLines.find((l) => l.includes('请帮我把'));
const chitchatIntent = chitchatRow?.split('|')[1] || '';
const taskIntent = taskRow?.split('|')[1] || '';

console.log(`[parsed] chitchat.intent="${chitchatIntent}" task.intent="${taskIntent}"`);

const chitchatOk = chitchatLen > 10;
const taskOk = taskLen > 50;
const chitchatIntentOk = chitchatIntent === 'chitchat';
const taskIntentOk = taskIntent === 'task' || taskIntent === 'knowledge';

console.log(
  `[result] chitchatResp=${chitchatOk} taskResp=${taskOk} chitchatIntent=${chitchatIntentOk} taskIntent=${taskIntentOk}`
);

const ok = chitchatOk && taskOk && chitchatIntentOk && taskIntentOk;
console.log(ok ? '✅ intent E2E 通过' : '❌ FAIL');
ws.close();
process.exit(ok ? 0 : 1);
