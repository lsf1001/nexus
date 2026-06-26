// Node ws 客户端,走 Vite 代理 (30077),看 confirmation_response 后多久会断
// 跟浏览器行为对齐:用 ws 库(类比浏览器原生 WebSocket,不主动 pong)
const WebSocket = require('ws');

const WS_URL = 'ws://localhost:30077/api/ws?token=nexus-default-token';
const PROMPT = '请直接调用 write_file 工具把内容 "node_proxy_diag" 写入 ~/.nexus/AGENTS.md。不要问任何问题。';

(async () => {
  console.log('Connecting to', WS_URL);
  const t0 = Date.now();
  const ws = new WebSocket(WS_URL, {
    // 模拟浏览器:不主动响应 ping
    autoPong: false,
    handshakeTimeout: 10000,
  });

  ws.on('open', () => {
    console.log(`[+${Date.now() - t0}ms] open`);
    ws.send(JSON.stringify({ type: 'message', content: PROMPT, title: 'node proxy diag' }));
  });
  ws.on('message', (data) => {
    const f = JSON.parse(data.toString());
    console.log(`[+${Date.now() - t0}ms] RX ${f.type}${f.event_id ? ` event_id=${f.event_id}` : ''}${f.content ? ` "${f.content.slice(0, 60)}"` : ''}`);
    if (f.type === 'confirmation_request') {
      console.log(`[+${Date.now() - t0}ms] TX confirmation_response approve`);
      ws.send(JSON.stringify({
        type: 'confirmation_response',
        event_id: f.event_id,
        interrupt_id: f.interrupt_id,
        decision: 'approve',
      }));
    }
  });
  ws.on('close', (code, reason) => {
    console.log(`[+${Date.now() - t0}ms] CLOSE code=${code} reason=${reason.toString()}`);
    process.exit(0);
  });
  ws.on('error', (err) => {
    console.log(`[+${Date.now() - t0}ms] ERROR: ${err.message}`);
  });
  ws.on('ping', (data) => {
    console.log(`[+${Date.now() - t0}ms] PING from server (autoPong=${false})`);
  });
  ws.on('pong', (data) => {
    console.log(`[+${Date.now() - t0}ms] PONG from server`);
  });

  setTimeout(() => {
    console.log(`[+${Date.now() - t0}ms] TIMEOUT 120s, no close`);
    process.exit(1);
  }, 120_000);
})();
