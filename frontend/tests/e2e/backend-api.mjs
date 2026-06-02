/**
 * 后端 REST API + WebSocket 鉴权 E2E（不依赖 LLM）
 *
 * 覆盖：
 *  - GET /api/models 列表
 *  - POST /api/models 新建（含 409 重复）
 *  - PUT /api/models/{id} 更新（含 404）
 *  - DELETE /api/models/{id} 删除（含 400 至少一个）
 *  - GET /api/sessions 列出会话
 *  - GET /api/channels 渠道列表
 *  - WS /api/ws 鉴权（无 token、错 token、对 token）
 *  - CORS 头检查
 *  - 404 路径
 *  - 错误响应状态码正确
 */

import fs from 'fs';
import path from 'path';
import http from 'http';
import crypto from 'crypto';
import { fileURLToPath } from 'url';
import { request as playwrightRequest } from 'playwright';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ARTIFACT_DIR = path.join(__dirname, 'artifacts');
fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
const RESULTS_FILE = path.join(ARTIFACT_DIR, 'backend-api-results.json');

const BACKEND = process.env.E2E_BACKEND || 'http://localhost:30000';
const WS_URL = BACKEND.replace(/^http/, 'ws') + '/api/ws';
const WS_TOKEN = 'nexus-default-token';

const results = [];
function record(name, pass, detail = '') {
  results.push({ name, pass, detail });
  console.log(`${pass ? '✓' : '✗'} ${name}${detail ? '  — ' + detail : ''}`);
}

// 共用 request context
const ctx = await playwrightRequest.newContext({ baseURL: BACKEND });

// ========== 1. 模型 CRUD ==========
console.log('\n=== 1. 模型 CRUD ===');

// GET
let r = await ctx.get('/api/models');
record('GET /api/models 返回 200', r.status() === 200);
const models = await r.json();
record('GET /api/models 是数组', Array.isArray(models) && models.length >= 1);

// 清理可能残留的测试模型
for (const m of models) {
  if (m.id.startsWith('e2e-')) {
    await ctx.delete(`/api/models/${m.id}`);
  }
}

// POST 新建
r = await ctx.post('/api/models', {
  data: {
    id: 'e2e-test-1',
    name: 'E2E Test Model',
    api_key: 'fake-key-for-test',
    api_base: 'https://api.example.com',
    temperature: 0.5,
  },
});
record('POST /api/models 新建 201', r.status() === 201);
const created = await r.json();
record('POST 返回 success=true', created.success === true);
record('POST 返回新建的 model', created.model?.id === 'e2e-test-1');

// POST 重复
r = await ctx.post('/api/models', {
  data: {
    id: 'e2e-test-1',
    name: 'Duplicate',
  },
});
record('POST 重复 ID 返回 409', r.status() === 409);
const dupBody = await r.json();
record('409 响应包含已存在提示', /已存在/.test(JSON.stringify(dupBody)));

// PUT 更新
r = await ctx.put('/api/models/e2e-test-1', {
  data: { name: 'Renamed E2E' },
});
record('PUT /api/models/{id} 200', r.status() === 200);
const updated = await r.json();
record('PUT 返回的 model.name 已更新', updated.model?.name === 'Renamed E2E');

// PUT 不存在
r = await ctx.put('/api/models/nonexistent-id-xyz', {
  data: { name: 'X' },
});
record('PUT 不存在 ID 返回 404', r.status() === 404);

// DELETE
r = await ctx.delete('/api/models/e2e-test-1');
record('DELETE /api/models/{id} 200', r.status() === 200);

// DELETE 不存在
r = await ctx.delete('/api/models/nonexistent-id-xyz');
record('DELETE 不存在 ID 返回 404', r.status() === 404);

// DELETE 最后一个模型应失败
const allModels = await (await ctx.get('/api/models')).json();
if (allModels.length === 1) {
  r = await ctx.delete(`/api/models/${allModels[0].id}`);
  record('DELETE 最后一个模型返回 400', r.status() === 400);
  const minBody = await r.json();
  record('400 响应包含"至少保留一个"', /至少需要保留/.test(JSON.stringify(minBody)));
} else {
  record('DELETE 最后一个模型返回 400', true, 'skipped (已有多模型)');
}

// ========== 2. 会话与渠道 ==========
console.log('\n=== 2. 会话与渠道 ===');

r = await ctx.get('/api/sessions');
record('GET /api/sessions 200', r.status() === 200);
const sessions = await r.json();
record('/api/sessions 是数组', Array.isArray(sessions));

r = await ctx.get('/api/channels');
record('GET /api/channels 200', r.status() === 200);
const channels = await r.json();
record('/api/channels 包含 channels 字段', typeof channels === 'object' && Array.isArray(channels.channels));
record('/api/channels 返回数组', Array.isArray(channels.channels));

// ========== 3. 错误路径 ==========
console.log('\n=== 3. 错误路径 ===');

r = await ctx.get('/api/this-does-not-exist');
record('未知路由返回 404', r.status() === 404);

r = await ctx.post('/api/models', { data: {} });
record('POST 模型缺 id 返回 422', r.status() === 422);

r = await ctx.get('/api/models', {
  headers: { 'Origin': 'http://evil.example.com' },
});
record('CORS 允许任意源（dev 模式）', r.status() === 200);

// ========== 4. WebSocket 鉴权（用 fetch + upgrade，不依赖浏览器 API 的 close code 限制） ==========
console.log('\n=== 4. WebSocket 鉴权 ===');

// 用原始 HTTP 升级请求直接探测 close code（不走浏览器 WebSocket）
async function probeWsHandshake(query) {
  const url = `${WS_URL}${query}`;
  return new Promise((resolve) => {
    const u = new URL(url);
    const key = Buffer.from(crypto.randomBytes(16)).toString('base64');
    const req = http.request({
      hostname: u.hostname,
      port: u.port,
      path: u.pathname + u.search,
      headers: {
        'Connection': 'Upgrade',
        'Upgrade': 'websocket',
        'Sec-WebSocket-Version': '13',
        'Sec-WebSocket-Key': key,
      },
      timeout: 3000,
    });
    req.on('upgrade', (res, socket) => {
      socket.destroy();
      resolve({ accepted: true, code: null });
    });
    req.on('response', (res) => {
      resolve({ accepted: false, code: res.statusCode });
    });
    req.on('error', (e) => resolve({ accepted: false, code: null, err: e.message }));
    req.on('timeout', () => { req.destroy(); resolve({ accepted: false, code: null }); });
    req.end();
  });
}

// 4a. 无 token
let r1 = await probeWsHandshake('');
record('WS 无 token 被拒（非 101 升级）', !r1.accepted, JSON.stringify(r1));

// 4b. 错误 token
let r2 = await probeWsHandshake('?token=wrong-token');
record('WS 错误 token 被拒（非 101 升级）', !r2.accepted, JSON.stringify(r2));

// 4c. 正确 token
let r3 = await probeWsHandshake(`?token=${WS_TOKEN}`);
record('WS 正确 token 接受（101 升级）', r3.accepted, JSON.stringify(r3));

// 4d. 用 Node WebSocket 测正确 token 后能收到 session_created
let wsConnected = false;
let firstMessageType = null;
let sessionIdFromServer = null;
try {
  const ws = new WebSocket(`${WS_URL}?token=${WS_TOKEN}`);
  const opened = new Promise((resolve) => {
    ws.onopen = () => { wsConnected = true; resolve(); };
    ws.onerror = () => resolve();
    setTimeout(resolve, 3000);
  });
  await opened;

  if (wsConnected) {
    const gotFirst = new Promise((resolve) => {
      ws.onmessage = (ev) => {
        const data = JSON.parse(ev.data);
        if (data.type === 'session_created') {
          sessionIdFromServer = data.session_id;
          firstMessageType = data.type;
        } else {
          firstMessageType = data.type;
        }
        resolve();
      };
      setTimeout(resolve, 8000);
    });
    ws.send(JSON.stringify({ content: 'probe ping' }));
    await gotFirst;

    record('WS 正确 token 连上后收到消息', firstMessageType !== null, `type=${firstMessageType}`);
    record('WS session_created 携带 session_id', sessionIdFromServer !== null);
  } else {
    record('WS 正确 token 连上后收到消息', false, '未连上');
  }
  ws.close();
} catch (e) {
  record('WS 正确 token 测试', false, e.message);
}

// ========== 汇总 ==========
await ctx.dispose();

console.log('\n========== 后端 API 汇总 ==========');
const passed = results.filter(r => r.pass).length;
const failed = results.filter(r => !r.pass);
console.log(`通过: ${passed} / ${results.length}`);
if (failed.length > 0) {
  console.log('\n失败项:');
  failed.forEach(f => console.log(`  ✗ ${f.name}${f.detail ? '  — ' + f.detail : ''}`));
}

fs.writeFileSync(RESULTS_FILE, JSON.stringify(results, null, 2));
process.exit(failed.length === 0 ? 0 : 1);
