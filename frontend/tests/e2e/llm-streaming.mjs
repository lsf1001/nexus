/**
 * 真 LLM 流式响应 E2E
 *
 * 前置：后端进程已配置真实 API Key（MINIMAX_API_KEY 或 ANTHROPIC_AUTH_TOKEN）
 * 通过：E2E_BACKEND 环境变量或默认 localhost:30000 找到后端
 *
 * 覆盖：
 *  - WS 提交消息后能收到 session_created
 *  - 收到多个 chunk 事件（流式）
 *  - 收到 final 事件（完整内容）
 *  - 收到 done 事件（流结束）
 *  - chunk 累积 = final 内容
 *  - 同一会话第二轮能基于上下文继续
 *  - 思考过程事件（如果模型支持）
 *  - 空消息不触发任何事件
 *  - 超长消息仍能完成
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ARTIFACT_DIR = path.join(__dirname, 'artifacts');
fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
const RESULTS_FILE = path.join(ARTIFACT_DIR, 'llm-streaming-results.json');

const BACKEND_HTTP = process.env.E2E_BACKEND || 'http://localhost:30000';
const WS_URL = BACKEND_HTTP.replace(/^http/, 'ws') + '/api/ws';
const WS_TOKEN = 'nexus-default-token';

const results = [];
function record(name, pass, detail = '') {
  results.push({ name, pass, detail });
  console.log(`${pass ? '✓' : '✗'} ${name}${detail ? '  — ' + detail : ''}`);
}

const WS = globalThis.WebSocket;

function openWs() {
  return new Promise((resolve, reject) => {
    const ws = new WS(`${WS_URL}?token=${WS_TOKEN}`);
    const t = setTimeout(() => reject(new Error('connect timeout')), 5000);
    ws.onopen = () => { clearTimeout(t); resolve(ws); };
    ws.onerror = (e) => { clearTimeout(t); reject(new Error('connect error')); };
  });
}

function collectEvents(ws, donePredicate, timeoutMs = 90000) {
  return new Promise((resolve) => {
    const events = [];
    const timer = setTimeout(() => resolve(events), timeoutMs);
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        events.push(data);
        if (donePredicate(data)) {
          clearTimeout(timer);
          resolve(events);
        }
      } catch (e) { /* ignore */ }
    };
  });
}

// ========== 1. 基础流式响应 ==========
console.log('\n=== 1. 基础流式响应 ===');
let sessionId = null;
let allEvents = [];
let ws1;

try {
  ws1 = await openWs();
  record('WS 连接成功', true);

  const collectP = collectEvents(ws1, (e) => e.type === 'done' || e.type === 'error', 60000);
  ws1.send(JSON.stringify({ content: '用一句话回答：1+1=?' }));
  allEvents = await collectP;

  const types = allEvents.map(e => e.type);
  console.log('  收到事件:', types.join(','));
  record('收到 session_created', types.includes('session_created'));
  record('收到 chunk 事件', types.filter(t => t === 'chunk').length > 0, `chunks=${types.filter(t => t === 'chunk').length}`);
  record('收到 final 事件', types.includes('final'));
  record('收到 done 事件', types.includes('done'), `error=${types.includes('error')}`);

  const sc = allEvents.find(e => e.type === 'session_created');
  sessionId = sc?.session_id;

  const chunkSum = allEvents.filter(e => e.type === 'chunk').map(e => e.content || '').join('');
  const finalContent = allEvents.find(e => e.type === 'final')?.content || '';
  record('chunk 累积与 final 一致', chunkSum === finalContent, `chunkLen=${chunkSum.length} finalLen=${finalContent.length}`);
  record('final 内容非空', finalContent.length > 0, `len=${finalContent.length}`);
  record('final 含 "2"（答案）', /2/.test(finalContent), `"${finalContent.slice(0, 80)}"`);

  ws1.close();
} catch (e) {
  record('基础流式响应', false, e.message);
  try { ws1?.close(); } catch {}
}

// ========== 2. 多轮对话（同一 session） ==========
console.log('\n=== 2. 多轮对话（同一 session） ===');
if (sessionId) {
  let ws2;
  try {
    ws2 = await openWs();
    const collectP = collectEvents(ws2, (e) => e.type === 'done' || e.type === 'error', 60000);
    ws2.send(JSON.stringify({ content: '再回答：2+2=?', session_id: sessionId }));
    const events = await collectP;

    const types = events.map(e => e.type);
    record('第二轮收到 final', types.includes('final'));
    record('第二轮收到 done', types.includes('done'));
    const final2 = events.find(e => e.type === 'final')?.content || '';
    record('第二轮 final 含 "4"', /4/.test(final2), `"${final2.slice(0, 50)}"`);

    ws2.close();
  } catch (e) {
    record('多轮对话', false, e.message);
    try { ws2?.close(); } catch {}
  }
} else {
  record('多轮对话（同一 session）', false, 'no session_id from round 1');
}

// ========== 3. 思考过程事件 ==========
console.log('\n=== 3. 思考过程事件 ===');
if (sessionId) {
  let ws3;
  try {
    ws3 = await openWs();
    const collectP = collectEvents(ws3, (e) => e.type === 'done' || e.type === 'error', 60000);
    ws3.send(JSON.stringify({ content: '思考过程测试：列出 3 个水果', session_id: sessionId }));
    const events = await collectP;

    const types = events.map(e => e.type);
    const hasThinking = types.includes('thinking');
    if (hasThinking) {
      record('收到 thinking 事件', true, `${types.filter(t => t === 'thinking').length} 个`);
    } else {
      record('未收到 thinking（模型可能不支持）', true, 'skipped');
    }
    record('思考过程测试收到 final', types.includes('final'));

    ws3.close();
  } catch (e) {
    record('思考过程', false, e.message);
    try { ws3?.close(); } catch {}
  }
}

// ========== 4. 错误路径 ==========
console.log('\n=== 4. 错误路径 ===');
{
  let ws4;
  try {
    ws4 = await openWs();

    // 发空消息——后端应当 ignore
    let emptyFired = false;
    ws4.onmessage = () => { emptyFired = true; };
    ws4.send(JSON.stringify({ content: '' }));
    await new Promise(r => setTimeout(r, 2000));
    record('空消息不发任何事件', !emptyFired, emptyFired ? '触发了事件' : 'no event');

    // 发一个超长消息
    const longMsg = '问题 ' + 'x'.repeat(2000);
    const collectP = collectEvents(ws4, (e) => e.type === 'done' || e.type === 'error', 60000);
    ws4.send(JSON.stringify({ content: longMsg, session_id: sessionId }));
    const events = await collectP;
    const types = events.map(e => e.type);
    record('超长消息仍能完成', types.includes('done') || types.includes('final'), `types=${types.join(',')}`);

    ws4.close();
  } catch (e) {
    record('错误路径', false, e.message);
    try { ws4?.close(); } catch {}
  }
}

// ========== 汇总 ==========
console.log('\n========== 真 LLM 流式 E2E 汇总 ==========');
const passed = results.filter(r => r.pass).length;
const failed = results.filter(r => !r.pass);
console.log(`通过: ${passed} / ${results.length}`);
if (failed.length > 0) {
  console.log('\n失败项:');
  failed.forEach(f => console.log(`  ✗ ${f.name}${f.detail ? '  — ' + f.detail : ''}`));
}

fs.writeFileSync(RESULTS_FILE, JSON.stringify({
  pass: passed,
  total: results.length,
  results,
  sessionId,
}, null, 2));

process.exit(failed.length === 0 ? 0 : 1);
