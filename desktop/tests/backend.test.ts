import assert from "node:assert/strict";
import net from "node:net";
import type { AddressInfo } from "node:net";
import { spawn } from "node:child_process";
import { describe, it } from "node:test";
import { buildDesktopCorsOrigins, findAvailablePort, findExistingBackend, stopBackend, waitForHealth } from "../src/backend.js";

describe("findExistingBackend", () => {
  it("returns the URL when /health responds ok on the preferred port", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => new Response("{}", { status: 200 })) as typeof fetch;

    try {
      const url = await findExistingBackend("127.0.0.1", 30000);
      assert.equal(url, "http://127.0.0.1:30000");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("returns null when no backend is listening on the preferred port", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => {
      throw new Error("connection refused");
    }) as typeof fetch;

    try {
      const url = await findExistingBackend("127.0.0.1", 51111);
      assert.equal(url, null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("returns null when /health responds non-ok (e.g. 500)", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => new Response("", { status: 500 })) as typeof fetch;

    try {
      const url = await findExistingBackend("127.0.0.1", 30000);
      assert.equal(url, null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});

describe("buildDesktopCorsOrigins", () => {
  it("includes the bound port so CORSMiddleware accepts desktop /api/* calls", () => {
    const origins = buildDesktopCorsOrigins(30000);
    // 默认端口命中 CORSMiddleware 白名单,desktop 启动后所有 REST/WS 都不会被预检拒绝
    assert.match(origins, /http:\/\/127\.0\.0\.1:30000/);
    assert.match(origins, /http:\/\/localhost:30000/);
    // 默认列表仍保留(用户已在浏览器开 30077 / 8000 场景不破)
    assert.match(origins, /http:\/\/127\.0\.0\.1:30077/);
    assert.match(origins, /tauri:\/\/localhost/);
  });

  it("reflects a port shifted by findAvailablePort (30000 occupied → 30001)", () => {
    // 复现真实场景:30000 被另一个 nexus 占,desktop 偏移到 30001。
    const origins = buildDesktopCorsOrigins(30001);
    assert.match(origins, /http:\/\/127\.0\.0\.1:30001/);
    assert.match(origins, /http:\/\/localhost:30001/);
    // 不应包含未使用的端口(避免误授权)
    assert.doesNotMatch(origins, /http:\/\/127\.0\.0\.1:30000[^0-9]/);
  });
});

describe("waitForHealth", () => {
  it("resolves when health endpoint returns ok", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => new Response("{}", { status: 200 })) as typeof fetch;

    try {
      await waitForHealth("http://127.0.0.1:30000", 1_000);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("rejects when backend never becomes healthy", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => {
      throw new Error("connection refused");
    }) as typeof fetch;

    try {
      await assert.rejects(
        () => waitForHealth("http://127.0.0.1:1", 50),
        /did not become healthy/
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});

describe("findAvailablePort", () => {
  it("skips an occupied preferred port", async () => {
    const server = net.createServer();

    await new Promise<void>((resolve) => {
      server.listen(0, "127.0.0.1", () => resolve());
    });

    try {
      const address = server.address();
      assert.equal(typeof address, "object");
      assert.ok(address);

      const occupiedPort = (address as AddressInfo).port;
      const availablePort = await findAvailablePort("127.0.0.1", occupiedPort);

      assert.equal(availablePort, occupiedPort + 1);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

describe("stopBackend", () => {
  it("kills a running child process via SIGTERM", async () => {
    // spawn 一个最简的 sleep 子进程,验证 stopBackend 能干净 kill 它。
    // 用 process.execPath (node 自身) + setInterval 保持长跑,比 sleep 更便携。
    const child = spawn(process.execPath, ["-e", "setInterval(()=>{}, 1000)"], {
      stdio: ["ignore", "pipe", "pipe"]
    });

    assert.ok(child.pid, "child process should have a pid");
    const pid = child.pid;

    // 确认子进程在跑
    assert.ok(process.kill(pid, 0), "child should be alive before stop");

    await stopBackend(child);

    // SIGTERM 后子进程应已退出
    assert.equal(child.killed, true, "child should be marked killed");
    // 进程已死 — process.kill(pid, 0) 抛 ESRCH
    assert.throws(() => process.kill(pid, 0), /ESRCH/);
  });

  it("escalates to SIGKILL if SIGTERM does not exit the child in time", async () => {
    // 故意忽略 SIGTERM 的子进程,验证 2s 兜底 SIGKILL 能强制清理。
    // signal handler 里只 reschedule,不退出。
    const child = spawn(process.execPath, [
      "-e",
      // 忽略 SIGTERM(用 signal 事件不退出),3s 后自然退出
      "process.on('SIGTERM', () => {}); setTimeout(() => process.exit(0), 5000);"
    ], {
      stdio: ["ignore", "pipe", "pipe"]
    });

    const pid = child.pid;
    assert.ok(pid);

    const start = Date.now();
    await stopBackend(child);
    const elapsed = Date.now() - start;

    // 应该 ~2s 触发 SIGKILL 兜底(我们的 SHUTDOWN_TIMEOUT_MS=2000)
    assert.ok(elapsed < 3500, `stopBackend should escalate within 2s, took ${elapsed}ms`);
    assert.equal(child.killed, true);
    assert.throws(() => process.kill(pid, 0), /ESRCH/);
  });

  it("is a no-op when called on an already-killed child", async () => {
    const child = spawn(process.execPath, ["-e", "setInterval(()=>{}, 1000)"], {
      stdio: ["ignore", "pipe", "pipe"]
    });
    child.kill("SIGKILL");
    // 等子进程死透
    await new Promise<void>((resolve) => child.once("exit", () => resolve()));

    // stopBackend 看到 killed=true 应立即返回
    const start = Date.now();
    await stopBackend(child);
    assert.ok(Date.now() - start < 50, "stopBackend should be instant on killed child");
  });
});
