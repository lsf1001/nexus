// 验证 quality judge 路径正常:发一个 200+ 字任务,等 quality gate 跑完
import { execSync } from 'node:child_process';
import WebSocket from 'ws';
import { writeFileSync, mkdirSync } from 'node:fs';
const OUT = '/tmp/nexus-quality';
mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const target = JSON.parse(execSync('curl -s http://127.0.0.1:9229/json/list').toString()).find(t => t.url === 'http://127.0.0.1:30000/app/');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => ws.on('open', r));
async function call(method, params={}) {
  const id = Math.floor(Math.random() * 1e9);
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve) => { const h = (d) => { const m = JSON.parse(d); if (m.id === id) { ws.off('message', h); resolve(m.result); } }; ws.on('message', h); });
}
async function ev(expr) { return (await call('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result.value; }

await call('Page.reload', { ignoreCache: true });
await sleep(3500);

// 选"新对话"
await ev(`document.querySelector('.btn-new-task')?.click()`);
await sleep(1500);

// focus + set value (long enough to bypass chitchat short-circuit)
await ev(`(() => { const ta = document.querySelector('.composer-textarea'); if (ta) { ta.focus(); ta.setSelectionRange(0, 0); } })()`);
await sleep(200);
const q = '请帮我详细分析一下 PostgreSQL 相比 MySQL 在事务隔离、MVCC 实现和索引结构方面的核心差异,以及在生产环境中选型时应该考虑哪些因素。';
await call('Input.insertText', { text: q });
await sleep(300);
console.log('[typed-len]', (await ev(`document.querySelector('.composer-textarea')?.value || ''`)).length);

// Enter
await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
await call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });

// 监控 35s — 长题 + judge + 可能 repair
console.log('监控 35s 等 quality gate 跑完...');
let finalSeen = false;
for (let i = 0; i < 35; i++) {
  await sleep(1000);
  const snap = await ev(`JSON.stringify({
    asstCount: document.querySelectorAll('[data-role="assistant"], .bubble-assistant, .message-assistant').length,
    asstLen: (() => { const arr = document.querySelectorAll('[data-role="assistant"], .bubble-assistant, .message-assistant'); return arr.length > 0 ? arr[arr.length - 1].textContent.length : 0; })(),
    sendBtnDisabled: document.querySelector('.send-button')?.disabled,
  })`);
  const s = JSON.parse(snap);
  if (s.asstLen > 50) { console.log(`t+${i+1}s asst len=${s.asstLen} disabled=${s.sendBtnDisabled}`); }
  if (s.asstLen > 200 && !s.sendBtnDisabled) { finalSeen = true; break; }
}

const finalState = await ev(`JSON.stringify({
  asstContents: Array.from(document.querySelectorAll('[data-role="assistant"], .bubble-assistant, .message-assistant')).map(e => e.textContent?.trim().slice(0, 100)),
  sendBtnDisabled: document.querySelector('.send-button')?.disabled,
})`);
console.log('FINAL:', finalState);
const scr = await call('Page.captureScreenshot', { format: 'png' });
writeFileSync(`${OUT}/final.png`, Buffer.from(scr.data, 'base64'));

const f = JSON.parse(finalState);
const ok = finalSeen || (f.asstContents.some(c => c && c.length > 50) && !f.sendBtnDisabled);
console.log(ok ? '✅ quality gate 跑通,长题完整输出' : '❌ FAIL');
ws.close();
process.exit(ok ? 0 : 1);
