use std::env;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    tauri_build::build();

    // Generate OUT_DIR/ws_token.rs so binary embeds a build-time random token.
    //
    // 优先级:
    //   1. env BUILD_WS_TOKEN (打包脚本可控:scripts/build_dmg.sh 可读 ~/.build_token 注入)
    //   2. desktop/src-tauri/.build_token (持久化,跨 build 复用 → 老用户 DMG 重装 token 不变)
    //   3. openssl rand -hex 32 生成新值,首次写入 .build_token
    //
    // WHY 持久化:用户已经在 /Applications/Nexus.app 跑过一次 DMG,bundle 里的 token
    // 跟前端 baked-in 的是同一字符串(由 build.rs 在编译期固化)。重打时若 env 没给,
    // 仍用同一个 .build_token,保证"重打后 token 不变",避免老用户授权失效。
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let token_path = manifest_dir.join(".build_token");

    let token = if let Ok(t) = env::var("BUILD_WS_TOKEN") {
        if t.is_empty() {
            read_or_generate_token(&token_path)
        } else {
            t
        }
    } else {
        read_or_generate_token(&token_path)
    };

    let out_dir = std::env::var("OUT_DIR").expect("OUT_DIR set by cargo");
    let dest = std::path::PathBuf::from(out_dir).join("ws_token.rs");
    let mut f = fs::File::create(&dest).expect("create OUT_DIR/ws_token.rs");
    writeln!(f, "pub const WS_TOKEN: &str = \"{token}\";\n").expect("write ws_token.rs");

    // 触发重编译:env 改变或 .build_token 内容改变
    println!("cargo:rerun-if-env-changed=BUILD_WS_TOKEN");
    println!("cargo:rerun-if-changed={}", token_path.display());
}

fn read_or_generate_token(token_path: &PathBuf) -> String {
    if token_path.exists() {
        match fs::read_to_string(token_path) {
            Ok(s) => {
                let t = s.trim().to_string();
                if !t.is_empty() {
                    return t;
                }
                // 退化路径:空文件,重新生成
                eprintln!("[nexus] .build_token empty, regenerating");
            }
            Err(e) => {
                eprintln!("[nexus] read .build_token failed: {e}, regenerating");
            }
        }
    }
    let out = Command::new("openssl")
        .args(["rand", "-hex", "32"])
        .output()
        .expect("openssl rand -hex 32");
    let t = String::from_utf8(out.stdout)
        .expect("openssl stdout not utf-8")
        .trim()
        .to_string();
    fs::write(token_path, &t).expect("write .build_token");
    eprintln!("[nexus] generated new WS token → {}", token_path.display());
    t
}
