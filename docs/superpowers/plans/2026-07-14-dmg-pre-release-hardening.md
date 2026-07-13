# Nexus 上线前硬化 实施计划(WS token 随机化 + 内部清扫)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) 或 superpowers:executing-plans 来跑这条 plan 的 task 列表。Steps use checkbox (`- [ ]`) for tracking.

**Goal:** 把 DMG bundle 里的 WS 鉴权 token 从公开字符串 `nexus-default-token` 改成 build-time 随机生成的高强度 hex 串,固化到前端 bundle + sidecar runtime env,两端对齐。同时清理 `nexus/backend/config.py` 里"老 config.json ws_token 入口"的 fall-back(本就没用,显式 dead 更好)。再写 CHANGELOG 迁移说明、重打 DMG、装机验证。

**Architecture:** 用 `desktop/src-tauri/build.rs` 在每次 cargo build 时生成 `OUT_DIR/ws_token.rs`,内容是 `pub const WS_TOKEN: &str = "<hex>"`。hex 优先读 env `BUILD_WS_TOKEN`(让打包脚本可控),env 缺失则 fallback 到 openssl 随机 32 字节并把首次生成的值持久化到 `desktop/src-tauri/.build_token` —— 后续重打 DMG 复用同一 token,避免每次重打都让老用户的 bundle token 跟新 bundle 不匹配。`runtime.rs` `include!` 这个常量,`start_sidecar` 注入 sidecar env。`tauri.conf.json` `beforeBuildCommand` 加 `VITE_NEXUS_WS_TOKEN=$BUILD_WS_TOKEN`(从 `.build_token` 读),使前端 Vite build 时拿到同一字符串。前后端只信 env,`config.py` 删 fallback,env 缺失 → 启动失败(开发期 fail-fast 比静默后端 401 友好)。

**Tech Stack:** Rust(build.rs + include!)/ shell(脚本生成 + 持久化 token)/ Vite 编译期 env / FastAPI / PyInstaller sidecar。

**Constraint:** 任何 commit 必须 ruff + pytest 全过。`memory/nexus-ws-subprotocol-auth.md` 之前记的 `nexus-default-token` 临时方案 — 本任务正式收回。

---

## File Structure

### 修改
- `desktop/src-tauri/build.rs` — 增加生成 `OUT_DIR/ws_token.rs`
- `desktop/src-tauri/src/runtime.rs` — 用 `include!` 拿 token,不再硬编码字符串
- `desktop/src-tauri/tauri.conf.json` — `beforeBuildCommand` 前置 `export VITE_NEXUS_WS_TOKEN=$(cat .../.build_token)`
- `nexus/backend/config.py:72-74` — 删 `file_config.get("security", {}).get("ws_token", "nexus-default-token")` fallback,只保留 `os.environ.get("NEXUS_WS_TOKEN", "")`
- `CHANGELOG.md` — 加 "Pre-release hardening" 条目,记 WS token 随机化 + 老 `security.ws_token` 失效迁移说明

### 新增
- `desktop/src-tauri/.build_token` — 首次 `cargo build` 时由 build.rs 写入,hex 64 字符;`.gitignore`
- `desktop/src-tauri/.gitignore` — 加 `.build_token`

---

## Task 1: 后端 `config.py` 收紧 ws_token 入口

**Files:**
- Modify: `nexus/backend/config.py:72-74`

- [ ] **Step 1: 写失败测试 / 验证动机**

`tests/` 下加一个 test 验证:当 `NEXUS_WS_TOKEN` 未设,`config["ws_token"]` 是空串(而不是 `"nexus-default-token"`)。

跑当前测试:`.venv/bin/pytest tests/ -q` — 通过则说明当前默认行为就是错的(给了不该有的"安全"假象)。

- [ ] **Step 2: 修改 `config.py:72-74`**

```python
"ws_token": os.environ.get("NEXUS_WS_TOKEN", ""),
```

删 fallback 那一长串。`config.py` 文案注释里说明 "为空时 sidecar 启动/WS 鉴权 fail-fast"。

- [ ] **Step 3: 跑 pytest**

`.venv/bin/pytest tests/ -q` 必过。

- [ ] **Step 4: ruff check + format**

`.venv/bin/ruff check nexus/ tests/ && .venv/bin/ruff format --check nexus/ tests/`

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/config.py tests/
git commit -m "fix(backend): ws_token 默认值删 fallback,env 缺失 → 空串"
```

WHY 写进 commit message(且要触发 fail-fast,不是默默降级)。

---

## Task 2: desktop `build.rs` 固化随机 token

**Files:**
- Modify: `desktop/src-tauri/build.rs`
- New: `desktop/src-tauri/.build_token`(gitignore,运行时生成)

- [ ] **Step 1: 写 `build.rs`**

读 `BUILD_WS_TOKEN` env(env 由打包脚本注入);env 缺失时:
1. 读 `desktop/src-tauri/.build_token`(持久化);不存在则 `openssl rand -hex 32` 生成,首次写入该文件
2. 后续 cargo build 复用 `.build_token`

写 `OUT_DIR/ws_token.rs`:
```rust
pub const WS_TOKEN: &str = "<token>";
```

`build.rs` 完整代码附在 plan 后(见 Appendix A)。

- [ ] **Step 2: cargo build 验证**

`cd desktop/src-tauri && cargo build` → 检查 `target/release/build/nexus-desktop-*/output` 或 `OUT_DIR` 里 `ws_token.rs` 内容含 `pub const WS_TOKEN:`。

- [ ] **Step 3: 验证 `.build_token` 内容**

`cat desktop/src-tauri/.build_token` → 64 hex 字符。

- [ ] **Step 4: 加 `.gitignore`**

`desktop/src-tauri/.gitignore` 加一行:
```
.build_token
```

- [ ] **Step 5: Commit**

```bash
git add desktop/src-tauri/build.rs desktop/src-tauri/.gitignore
git commit -m "feat(desktop): build.rs 固化随机 WS token(env + 持久化 .build_token)"
```

---

## Task 3: `runtime.rs` + `tauri.conf.json` 同步 token

**Files:**
- Modify: `desktop/src-tauri/src/runtime.rs`
- Modify: `desktop/src-tauri/tauri.conf.json`

- [ ] **Step 1: 改 `runtime.rs`**

把硬编码字符串 `"nexus-default-token"` 替换为 `include!(concat!(env!("OUT_DIR"), "/ws_token.rs"));` 取到的常量 `WS_TOKEN`,再 `cmd.env("NEXUS_WS_TOKEN", WS_TOKEN)`。

更新注释:删除"硬编码是临时方案"那段。

- [ ] **Step 2: 改 `tauri.conf.json` `beforeBuildCommand`**

```json
"beforeBuildCommand": "TOKEN=$(cat $(dirname $(realpath .))/../src-tauri/.build_token 2>/dev/null || openssl rand -hex 32 > $(dirname $(realpath .))/../src-tauri/.build_token && cat $(dirname $(realpath .))/../src-tauri/.build_token); export VITE_TAURI=true VITE_NEXUS_WS_TOKEN=$TOKEN; npm --prefix /Users/yxb/projects/nexus/frontend run build && rm -rf /Users/yxb/projects/nexus/desktop/src-tauri/frontend-dist && mkdir /Users/yxb/projects/nexus/desktop/src-tauri/frontend-dist && cp -R /Users/yxb/projects/nexus/frontend/dist/. /Users/yxb/projects/nexus/desktop/src-tauri/frontend-dist/"
```

(注:路径简化版 = `cd desktop/src-tauri && TOKEN=$(cat .build_token 2>/dev/null || (openssl rand -hex 32 > .build_token && cat .build_token)); export VITE_TAURI=true VITE_NEXUS_WS_TOKEN=$TOKEN && npm --prefix $ROOT/frontend run build && ...`。)

- [ ] **Step 3: cargo build 验证**

`cd desktop/src-tauri && cargo build` 编译过,没编译错误。

- [ ] **Step 4: 验字符串已替换**

`strings target/release/nexus-desktop | grep -E "^nexus-default-token$"` → **空**(证明硬编码字符串已下线)。

`strings target/release/nexus-desktop | grep -c "WS_TOKEN"` → `> 0`(证明新常量在 binary 里)。

- [ ] **Step 5: Commit**

```bash
git add desktop/src-tauri/src/runtime.rs desktop/src-tauri/tauri.conf.json
git commit -m "fix(desktop): runtime 注入常量 WS_TOKEN,beforeBuildCommand 注 VITE_NEXUS_WS_TOKEN"
```

---

## Task 4: CHANGELOG + 重打 DMG + 装机验证

**Files:**
- Modify: `CHANGELOG.md`
- New:(无需新文件,但需要 `release/Nexus-1.x.0-arm64.dmg` 重打)

- [ ] **Step 1: CHANGELOG 加条目**

```markdown
## [Unreleased] — Pre-release hardening

### WS 鉴权 token 随机化(breaking)
- DMG bundle 内 WS 鉴权 token 由公开字符串 `nexus-default-token` 改为 build-time 随机生成(64 hex 字符),固化到前端 bundle + sidecar runtime env。
- **`nexus/backend/config.py` `ws_token` 入口收紧**:仅读 env `NEXUS_WS_TOKEN`,缺省 → 空串(`start_sidecar` 强制注入,所以正常运行)。
- **迁移提示**:`~/.nexus/config.json` 的 `security.ws_token` 字段被移除生效路径(前端 baked-in 该值才是真值;该字段一直无效,显式 dead)。
```

- [ ] **Step 2: 跑全量测试**

`.venv/bin/pytest tests/ -q`(后端) + `cd frontend && npm run lint`(前端)。都过。

- [ ] **Step 3: 重打 DMG**

`bash scripts/build_dmg.sh 2>&1 | tail -30`,确认:
- `>>> step 2: cargo tauri build...` 内 `beforeBuildCommand` 跑出 `VITE_NEXUS_WS_TOKEN=<新 hex>` 字样
- 产出 `release/Nexus-1.1.0-arm64.dmg` 重建成功

- [ ] **Step 4: 验字符串已下线**

```bash
strings desktop/src-tauri/target/release/bundle/macos/Nexus.app/Contents/Resources/_up_/_up_/release/nexus-runtime/nexus-runtime | grep -c "nexus-default-token"
```

应该是 `0`(sidecar binary 里再没有公开 token 字面)。

frontend-dist JS bundle 里也应找不到 `nexus-default-token` 字符串。

- [ ] **Step 5: 装到 /Applications + 端到端验证**

```bash
kill 旧 PID → 卸 /Applications/Nexus.app → 重装新 DMG → open /Applications/Nexus.app
sleep 5
curl -X PUT -H "Authorization: Bearer <新 token>" http://127.0.0.1:30000/api/models/default ... → 200
curl -H "Authorization: Bearer nexus-default-token" http://127.0.0.1:30000/api/model → 401(证明老 token 失效)
```

- [ ] **Step 6: 用户视角 smoke**

`.venv/bin/python scripts/test_clarification_live.py "一句话:你是谁"` —— 流式回复命中 MiniMax-M3,UI 显示正常。

- [ ] **Step 7: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG 记 DMG pre-release hardening (WS token random)"
```

---

## Appendix A: build.rs 完整代码

```rust
// desktop/src-tauri/build.rs
// 生成 OUT_DIR/ws_token.rs,内容是固化 WS 鉴权 token。
//
// 优先级:
//   1. env BUILD_WS_TOKEN (打包脚本可控)
//   2. desktop/src-tauri/.build_token (持久化,跨 build 复用)
//   3. openssl rand -hex 32 生成新值,首次写入 .build_token

use std::env;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    tauri_build::build();

    // 找 desktop/src-tauri/.build_token (与 Cargo.toml 同级)
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let token_path = manifest_dir.join(".build_token");

    // 1) BUILD_WS_TOKEN env
    // 2) .build_token 持久化
    // 3) openssl rand -hex 32 生成
    let token = if let Ok(t) = env::var("BUILD_WS_TOKEN") {
        if t.is_empty() {
            return_outer_token(&token_path)
        } else {
            t
        }
    } else {
        return_outer_token(&token_path)
    };

    // 写到 OUT_DIR/ws_token.rs
    let out_dir = PathBuf::from(env!("OUT_DIR"));
    let dest = out_dir.join("ws_token.rs");
    let mut f = fs::File::create(&dest).expect("create ws_token.rs");
    writeln!(f, "pub const WS_TOKEN: &str = \"{token}\";").expect("write ws_token.rs");

    println!("cargo:rerun-if-env-changed=BUILD_WS_TOKEN");
    println!("cargo:rerun-if-changed={}", token_path.display());
}

fn return_outer_token(token_path: &PathBuf) -> String {
    if token_path.exists() {
        fs::read_to_string(token_path)
            .expect("read .build_token")
            .trim()
            .to_string()
    } else {
        let out = Command::new("openssl")
            .args(["rand", "-hex", "32"])
            .output()
            .expect("openssl rand -hex 32");
        let t = String::from_utf8(out.stdout).expect("utf8").trim().to_string();
        fs::write(token_path, &t).expect("write .build_token");
        t
    }
}

fn tauri_build_build() {
    tauri_build::build();
}
```

## Appendix B: tauri.conf.json beforeBuildCommand 简化版

由于 `tauri.conf.json` 的 `beforeBuildCommand` 是单个 shell 字符串,跨平台有 `realpath` 依赖问题,建议把 token 加载拆到外层 `scripts/build_dmg.sh`,在打 DMG 前先把 `desktop/src-tauri/.build_token` 准备好。具体:

```json
"beforeBuildCommand": "npm --prefix /Users/yxb/projects/nexus/frontend run build && rm -rf /Users/yxb/projects/nexus/desktop/src-tauri/frontend-dist && mkdir /Users/yxb/projects/nexus/desktop/src-tauri/frontend-dist && cp -R /Users/yxb/projects/nexus/frontend/dist/. /Users/yxb/projects/nexus/desktop/src-tauri/frontend-dist/"
```

并在 `scripts/build_dmg.sh` step 2 之前加:
```bash
# 确保 .build_token 存在(否则 build.rs fallback 自己创建)
TOKEN_FILE="$ROOT_DIR/desktop/src-tauri/.build_token"
if [ ! -f "$TOKEN_FILE" ]; then
  openssl rand -hex 32 > "$TOKEN_FILE"
  echo ">>> 生成 WS token: $TOKEN_FILE"
fi
export VITE_NEXUS_WS_TOKEN=$(cat "$TOKEN_FILE")
```

`cargo tauri build` 启动前 `beforeBuildCommand` 跑 npm 时,Vite 已经通过 `VITE_NEXUS_WS_TOKEN` 拿到 token — 走 env 链路。`start_sidecar` 走 `build.rs` 嵌入常量(后者走 env BUILD_WS_TOKEN 路径,如果打包脚本同时 export 这个会更稳)。

最终推荐:**两路并用** — `build.rs` 用 `env!("BUILD_WS_TOKEN")` 在编译期注入常量(优先级最高),`beforeBuildCommand` 用 `VITE_NEXUS_WS_TOKEN` 环境变量(由打包脚本 export)。两者都从 `.build_token` 取值,值相同。
