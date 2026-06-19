// DMG 真实 GUI 回归 - 重置式
import WebSocket from 'ws';
import { execSync } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';

const TARGET_URL = 'http://127.0.0.1:30000/app/';
const OUT = '/tmp/nexus-regression';
mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const log = (k, v) => console.log(`[${k}]`, typeof v === 'string' ? v : JSON.stringify(v));

function findNexusTarget() {
  const raw = execSync('curl -s http://127.0.0.1:9229/json/list').toString();
  return JSON.parse(raw).find(t => t.url === TARGET_URL);
}

async function main() {
  const target = findNexusTarget();
  if (!target) { console.error('NEXUS target not found'); process.exit(2); }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.on('open', r));

  let nextId = 1;
  const pending = new Map();
  ws.on('message', d => {
    const m = JSON.parse(d);
    if (m.id && pending.has(m.id)) {
      const { resolve, reject } = pending.get(m.id);
      pending.delete(m.id);
      m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result);
    }
  });
  const call = (method, params = {}) => {
    const id = nextId++;
    ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error(`timeout: ${method}`)); } }, 15000);
    });
  };
  const evalJS = async (expr) => (await call('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result.value;
  const screenshot = async (name) => {
    const r = await call('Page.captureScreenshot', { format: 'png' });
    const path = `${OUT}/${name}.png`;
    writeFileSync(path, Buffer.from(r.data, 'base64'));
    return path;
  };

  // 完全重置:硬刷新
  await call('Page.reload', { ignoreCache: true });
  await sleep(3500);
  const onChat0 = await evalJS(`!!document.querySelector('.composer-textarea')`);
  log('init-on-chat', onChat0);
  await screenshot('00-init');

  // R1: sidebar titles
  const titles = await evalJS(`Array.from(document.querySelectorAll('.task-item .task-item-body strong')).map(e => e.textContent.trim())`);
  log('R1-titles', titles);
  const r1Ok = titles.includes('回归测试标题');
  log('R1-title-fix-ok', r1Ok);

  // R2: 进设置
  await evalJS(`document.querySelector('.sidebar-settings-btn').click()`);
  await sleep(1500);
  const r2State = await evalJS(`JSON.stringify({
    hasSettingsView: !!document.querySelector('.settings-view'),
    hasWechatView: !!document.querySelector('.wechat-view'),
    backBtn: (() => { const b = document.querySelector('.back-btn[aria-label="返回聊天"]'); return b ? { text: b.textContent.trim(), visible: b.offsetParent !== null } : null; })()
  })`);
  log('R2-state', r2State);
  await screenshot('01-settings');
  const r2 = JSON.parse(r2State);
  const r2Ok = r2.hasSettingsView && r2.backBtn?.visible;

  // R3: 返回
  if (r2Ok) {
    await evalJS(`document.querySelector('.back-btn[aria-label="返回聊天"]').click()`);
    await sleep(1200);
    const onChat = await evalJS(`!!document.querySelector('.composer-textarea')`);
    log('R3-on-chat', onChat);
    await screenshot('02-back');
  }

  // R4: 微信
  await evalJS(`document.querySelector('.footer-link--wechat').click()`);
  await sleep(1500);
  const r4State = await evalJS(`JSON.stringify({
    hasWechatView: !!document.querySelector('.wechat-view'),
    backBtn: (() => { const b = document.querySelector('.wechat-header .back-btn, .back-btn[aria-label="返回聊天"]'); return b ? { text: b.textContent.trim(), visible: b.offsetParent !== null } : null; })()
  })`);
  log('R4-state', r4State);
  await screenshot('03-wechat');
  const r4 = JSON.parse(r4State);
  const r4Ok = r4.hasWechatView && r4.backBtn?.visible;

  // R5: 微信返回
  if (r4Ok) {
    await evalJS(`document.querySelector('.back-btn[aria-label="返回聊天"]').click()`);
    await sleep(1200);
    const onChat2 = await evalJS(`!!document.querySelector('.composer-textarea')`);
    log('R5-wechat-back', onChat2);
    await screenshot('04-wechat-back');
  }

  ws.close();
  const allOk = r1Ok && r2Ok && r4Ok;
  console.log('\n=== ' + (allOk ? '✅ ALL PASS' : '❌ FAILURES') + ' ===');
  console.log('R1 title:', r1Ok, '| R2 settings back:', r2Ok, '| R4 wechat back:', r4Ok);
  process.exit(allOk ? 0 : 1);
}

main().catch((e) => { console.error('FAIL', e); process.exit(1); });
