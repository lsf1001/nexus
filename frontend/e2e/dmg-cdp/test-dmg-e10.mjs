// 边界 10 修正版
import { execSync } from 'node:child_process';
import WebSocket from 'ws';
import { writeFileSync, mkdirSync } from 'node:fs';
const TARGET_URL = 'http://127.0.0.1:30000/app/';
const OUT = '/tmp/nexus-edges';
mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const target = JSON.parse(execSync('curl -s http://127.0.0.1:9229/json/list').toString()).find(t => t.url === TARGET_URL);
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => ws.on('open', r));
async function call(method, params={}) {
  const id = Math.floor(Math.random() * 1e9);
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve) => { const h = (d) => { const m = JSON.parse(d); if (m.id === id) { ws.off('message', h); resolve(m.result); } }; ws.on('message', h); });
}
async function ev(expr) { return (await call('Runtime.evaluate', { expression: expr, returnByValue: true })).result.value; }

await call('Page.reload', { ignoreCache: true });
await sleep(3500);
console.log('onChat:', await ev(`!!document.querySelector('.composer-textarea')`));

// 进设置
await ev(`document.querySelector('.sidebar-settings-btn')?.click()`);
await sleep(1200);
console.log('onSettings:', await ev(`!!document.querySelector('.settings-view')`));

// 点"当前模型"行的按钮
await ev(`(() => { const rows = document.querySelectorAll('.setting-row'); const r = Array.from(rows).find(x => x.textContent?.includes('当前模型')); const btn = r?.querySelector('button.toggle'); if (btn) btn.click(); return btn ? 'CLICKED' : 'NO_BTN'; })()`);
await sleep(1500);

// 找 modal: 用 z-50 或 fixed inset-0
const state = await ev(`JSON.stringify({
  hasModal: !!document.querySelector('.z-50, [class*="z-50"], [class*="fixed"][class*="inset-0"]'),
  modalHeader: document.querySelector('h2')?.textContent?.trim(),
  hasModelCard: !!document.querySelector('button:has(.font-semibold)'),
  text500: document.body.textContent.includes('模型配置'),
})`);
console.log('modal state:', state);

const r = JSON.parse(state);
const ok = r.hasModal && r.text500;
console.log(ok ? '✅ 边界10-模型modal弹出' : '❌ 边界10');

if (ok) {
  // 截图 + 关
  const scr = await call('Page.captureScreenshot', { format: 'png' });
  writeFileSync(`${OUT}/e10-fixed.png`, Buffer.from(scr.data, 'base64'));
}

ws.close();
