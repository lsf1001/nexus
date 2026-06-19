// 边界 11 重测:真实发长题,看 assistant 累积
import { execSync } from 'node:child_process';
import WebSocket from 'ws';
import { writeFileSync, mkdirSync } from 'node:fs';
const OUT = '/tmp/nexus-edges';
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
console.log('onChat:', await ev(`!!document.querySelector('.composer-textarea')`));

// 选 "新建对话"
await ev(`document.querySelector('.btn-new-task')?.click()`);
await sleep(2000);
console.log('onChat-after-new:', await ev(`!!document.querySelector('.composer-textarea')`));

// focus + 输入
await ev(`(() => { const ta = document.querySelector('.composer-textarea'); if (ta) { ta.focus(); ta.setSelectionRange(0, 0); } })()`);
await sleep(300);
const longQ = '请详细讲讲 transformer 的 self-attention 机制,包括 QKV 矩阵、scaled dot-product、multi-head 拆分,以及 positional encoding。控制在 500 字以内。';
await call('Input.insertText', { text: longQ });
await sleep(300);
const taVal = await ev(`document.querySelector('.composer-textarea')?.value || ''`);
console.log('textarea len:', taVal.length, '前 30:', taVal.slice(0, 30));

// Enter
await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
await call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });

// 监控 60s
console.log('监控 60s...');
for (let i = 0; i < 60; i++) {
  await sleep(1000);
  const snap = await ev(`JSON.stringify({
    userCount: document.querySelectorAll('[data-role="user"], .bubble-user, .message-user').length,
    asstCount: document.querySelectorAll('[data-role="assistant"], .bubble-assistant, .message-assistant').length,
    asstPreviews: Array.from(document.querySelectorAll('[data-role="assistant"], .bubble-assistant, .message-assistant')).map(e => e.textContent?.trim().slice(0, 50)),
    msgHtml: Array.from(document.querySelectorAll('[data-role]')).map(e => ({ role: e.getAttribute('data-role'), text: e.textContent?.trim().slice(0, 30) })),
    inputEmpty: document.querySelector('.composer-textarea')?.value === '',
  })`);
  console.log(`t+${i+1}s`, snap);
  const s = JSON.parse(snap);
  if (s.asstCount > 0 && s.asstPreviews.some(t => t.length > 20)) {
    console.log('✅ 收到 assistant 内容');
    break;
  }
}

const final = await ev(`JSON.stringify({
  asstContents: Array.from(document.querySelectorAll('[data-role="assistant"], .bubble-assistant, .message-assistant')).map(e => e.textContent?.trim().slice(0, 200)),
  msgCount: document.querySelectorAll('[data-role]').length,
})`);
console.log('FINAL:', final);
const scr = await call('Page.captureScreenshot', { format: 'png' });
writeFileSync(`${OUT}/e11-fixed.png`, Buffer.from(scr.data, 'base64'));
ws.close();
