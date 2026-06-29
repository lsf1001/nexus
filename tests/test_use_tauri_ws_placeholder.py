"""回归测试:useTauriWs 的 ws_open Channel 必须把消息转给 onMessage。

WHY:2026-06 之前 useTauriWs.ts 把 ws_open 绑定的 Channel onmessage 写成占位
``() => {}``,而 ws_relay.rs 简化后 ws_open 是后端 WS 响应的**唯一**通道。
占位代码导致后端 done/final/error 帧全部丢失,前端 isLoading 永远 true → 转圈。

修复后 onmessage 必须调用 ``onMessageRef.current(message)``。本测试断言源码
+ 最近的 build 产物都包含转发逻辑,不再含空函数占位,防止该 bug 再次回潮。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SRC = REPO_ROOT / "frontend" / "src" / "hooks" / "useTauriWs.ts"
CHATAREA_SRC = REPO_ROOT / "frontend" / "src" / "components" / "ChatArea.tsx"
DIST_ASSETS = REPO_ROOT / "frontend" / "dist" / "assets"

# DMG 安装位置有两个,任何一处跑旧 build 都会让用户继续转圈。E2E 2026-06-28
# 教训:开发者 rebuild DMG 默认放 ~/Library/Caches/nexus/build/ 但 Launchpad 扫
# /Applications,容易遗漏。两处都查,避免「dist 修好、app 还是旧版」的盲区。
_APP_BUNDLE_DIST = Path("/Applications/Nexus.app/Contents/Resources/frontend-dist/assets")
_CACHE_BUNDLE_DIST = Path.home() / "Library/Caches/nexus/build/Nexus.app/Contents/Resources/frontend-dist/assets"

_INSTALLED_DIST_DIRS = [d for d in (_APP_BUNDLE_DIST, _CACHE_BUNDLE_DIST) if d.exists()]


def _read_hook_source() -> str:
    return HOOK_SRC.read_text(encoding="utf-8")


def test_hook_source_forwards_open_chunk_messages() -> None:
    """源码:openChunk.onmessage 必须调用 onMessageRef.current,不能是空函数占位。"""
    src = _read_hook_source()

    # 抓 openChunk.onmessage = ... 这一行(到分号/换行)
    match = re.search(
        r"openChunk\.onmessage\s*=\s*([\s\S]+?);\s*\n",
        src,
    )
    assert match, "未找到 openChunk.onmessage = ... 赋值,源码结构变了?"

    body = match.group(1)
    # 旧占位形态: () => {} 或 () => { /* 占位 */ }
    assert "占位" not in body, f"openChunk.onmessage 仍是占位函数(2026-06 已知 bug,会导致转圈): {body!r}"
    assert not re.search(r"=\s*\(\s*\)\s*=>\s*\{\s*\}", body), (
        f"openChunk.onmessage 是空函数占位(会导致后端响应丢失 → 转圈): {body!r}"
    )
    # 必须显式调用 onMessageRef.current(...),不是别的 ref / 直调 onMessage
    assert "onMessageRef.current" in body, f"openChunk.onmessage 必须把消息转给 onMessageRef.current,实际: {body!r}"


def test_hook_source_uses_single_bound_channel_for_session() -> None:
    """架构约束:send 不应再每次新建 Channel(那是旧 ws_relay 形态)。

    简化后 ws_relay.rs 一次绑定 Channel + 长期 rx_task;如果 send 再传临时
    Channel 会被 Rust 端忽略(签名不收),而且前端也接不到消息。
    """
    src = _read_hook_source()
    send_match = re.search(
        r"const send\s*=\s*async[\s\S]+?\};",
        src,
    )
    assert send_match, "未找到 send 函数体"
    send_body = send_match.group(0)
    # send 只能 invoke('ws_send', { sessionId, payload }),不能传 Channel
    assert "ws_send" in send_body, "send 应调用 ws_send"
    assert "new Channel" not in send_body, "send 不应新建 Channel — ws_relay 简化后 ws_open 已绑定,send 只发 payload"
    # onChunk 作为函数实参/对象 key 才算违规(注释里出现 onChunk 没关系)。
    # 修复前的形态: invoke('ws_send', { sessionId, onChunk: tmpChannel })
    assert not re.search(r"onChunk\s*[:=]", send_body), (
        "send 不应传 onChunk 形参 — Channel 生命周期 = ws session,不是 per-send"
    )


@pytest.mark.skipif(not DIST_ASSETS.exists(), reason="frontend/dist 未 build,跳过产物断言")
def test_built_bundle_does_not_contain_placeholder() -> None:
    """build 产物里不应有 ws_open Channel 空函数占位。

    修复前 dist 里有 ``message=()=>{}``(minify 后的占位),导致转圈;现在
    转发代码 minify 后形如 ``onmessage=e=>{o.current(e)}``,本断言防止构建
    用了未修复的源码却没被发现的回归。
    """
    js_files = list(DIST_ASSETS.glob("*.js"))
    assert js_files, f"{DIST_ASSETS} 下没有 .js 产物"
    # main bundle 包含 useTauriWs 逻辑(index-*.js);browser-*.js 是 useWebSocket 路径
    main_bundles = [p for p in js_files if p.name.startswith("index-")]
    assert main_bundles, "未找到 index-*.js 主 bundle"

    for bundle in main_bundles:
        text = bundle.read_text(encoding="utf-8")
        # 占位:空函数体跟在 onmessage 后面。minify 后 r.onmessage=()=>{} / ()=>{ }
        # 这里用更稳的检查:必须包含 onmessage 形如 "<id>.current(e)" 的转发
        # (修复后源码是 r.onmessage=e=>{o.current(e)},minify 后变量名会变,
        #  但 ".current(e)" 这个调用形式在 minify 后保留)
        assert ".current(e)" in text or "o.current(e)" in text, (
            f"{bundle.name} 中找不到 channel onmessage 转发代码 (形如 .current(e));build 可能没包含 useTauriWs 修复"
        )
        # 旧 bug 标志:onChunk 后是空函数(可能不是严格匹配,作为辅助)
        # 主要断言已由上面的 ".current(e)" 兜底


@pytest.mark.skipif(
    not _INSTALLED_DIST_DIRS,
    reason="未检测到已安装的 Nexus.app,跳过 DMG 资源断言",
)
def test_installed_dmg_bundles_have_forwarding_fix() -> None:
    """已安装的 DMG bundle 里必须含转发代码,不能是占位。

    教训:build 产物在 ``frontend/dist/`` 是新鲜的,但 ``/Applications/Nexus.app/``
    和 ``~/Library/Caches/nexus/build/Nexus.app/`` 装的是开发者打包时的旧 dist。
    漏掉任何一处,用户启动那处 app 就会继续转圈。本测试遍历所有检测到的
    安装位置,逐一断言含转发、不含占位。
    """
    for dist_dir in _INSTALLED_DIST_DIRS:
        main_bundles = sorted(dist_dir.glob("index-*.js"))
        assert main_bundles, f"{dist_dir} 下没有 index-*.js 主 bundle(DMG 装了一半?)"
        for bundle in main_bundles:
            text = bundle.read_text(encoding="utf-8")
            assert "占位" not in text, f"{bundle} 仍含「占位」字样(转圈 bug 在 DMG 里复发,需要重新 build + 复制)"
            assert ".current(e)" in text or "o.current(e)" in text, (
                f"{bundle} 缺 channel onmessage 转发代码(形如 .current(e));"
                f"用户在 {dist_dir} 启动后转圈,需重新同步 frontend/dist"
            )


def test_chunk_thinking_stop_spinner_early() -> None:
    """UX 修复:收到 thinking / 第一个 chunk 就停 spinner,不等 done。

    WHY 2026-06-28:后端 LLM 1-2s 就开始 streaming chunks,但 done 要等
    QualityPipeline + chain overhead(20-30s)才发。这期间用户看到 spinner
    一直转,以为"卡死"。修复:thinking / 第一个 chunk 就 setIsLoading(false),
    spinner 立即停,内容继续 streaming 累积。done 仍会再 disarm 一次(幂等)。
    """
    src = CHATAREA_SRC.read_text(encoding="utf-8")

    def _case_body(event: str) -> str:
        # 从 ``case 'xxx': {`` 开始,抓直到下一个 ``break;``(case 体内的最后一个)。
        # 非贪婪 [\s\S]+? 在 \s*break; 锚点前停下,不会被 case 内的嵌套 {} 干扰。
        m = re.search(rf"case\s+['\"]{event}['\"]\s*:\s*\{{([\s\S]+?)\s*break\s*;", src)
        assert m, f"未找到 case '{event}'"
        return m.group(1)

    for event in ("thinking", "chunk"):
        body = _case_body(event)
        assert "setIsLoading(false)" in body, f"{event} case 必须 setIsLoading(false),否则 streaming 期间用户以为没回复"
        assert "disarm" in body, f"{event} case 必须 disarm watchdog"


def test_model_switch_updates_store_modelname() -> None:
    """切模型后 store.modelName 必须更新,SettingsView 才会显示新模型。

    WHY 2026-06-28:之前 useStore.modelName 只有 useBootstrap 启动时设一次,
    handleSwitch 切完 reload models 但没调 setModelName → SettingsView 的
    「当前模型」按钮永远停在初始值 'MiniMax-M3',切到 agnes 也不变。
    修复:handleSwitch 立即 setModelName(active_model.name);loadModels 完成后
    从新 models 找 is_active 的再同步一次(兜底其他 reload 路径)。
    """
    modal = (REPO_ROOT / "frontend/src/components/ModelConfigModal.tsx").read_text(encoding="utf-8")

    # 1) Modal 必须订阅 setModelName
    assert "setModelName" in modal, "ModelConfigModal 必须订阅 setModelName 才能同步显示"

    # 2) handleSwitch 切完调 setModelName(active_model.name)
    handle_switch = re.search(
        r"const handleSwitch\s*=\s*async[\s\S]+?\};",
        modal,
    )
    assert handle_switch, "未找到 handleSwitch 函数体"
    body = handle_switch.group(0)
    assert "setModelName" in body, (
        "handleSwitch 切完必须调 setModelName(active_model.name),否则 SettingsView "
        "标题不更新。修复:在 success 分支里 await loadModels 之前立即 setModelName。"
    )

    # 3) loadModels 完成后从 models 找 is_active 调 setModelName
    load_models = re.search(
        r"const loadModels\s*=\s*useCallback\([\s\S]+?\}\s*,\s*\[",
        modal,
    )
    assert load_models, "未找到 loadModels 函数体"
    body = load_models.group(0)
    assert "setModelName" in body, (
        "loadModels 必须从 data.find(is_active) 同步 setModelName,作为兜底 "
        "(防止 handleSwitch 漏写、或者其他 reload 路径漏写导致 modelName 过期)"
    )
    assert "is_active" in body, "loadModels 必须按 is_active 找当前激活模型"


def test_ws_emit_chunk_realtime_not_buffered() -> None:
    """回归测试:ws 流式循环的 chunk 处理路径不能改成缓存模式。

    WHY 2026-06-28 教训:旧实现 ``full_response += content`` 把 chunk 缓存到流末,
    导致 agnes 慢模型场景前端 26s 收不到任何帧,用户体感"转圈"。
    修复:parser.feed(content) 直接 emit,ThinkingParser 实时解析后 send_json。

    2026-06-29 模块化拆分后,源文件从 ``api/ws.py`` 改为 ``api/ws/streaming.py``。
    """
    src = (REPO_ROOT / "nexus/backend/api/ws/streaming.py").read_text(encoding="utf-8")
    # 必须 import ThinkingParser
    assert "from ..thinking_parser import ThinkingParser" in src or "from .api.thinking_parser" in src, (
        "ws/streaming.py 必须 import ThinkingParser,实时 emit chunk"
    )
    # on_chat_model_stream 分支必须调用 parser.feed 并 send_json
    stream_match = re.search(
        r"event_type\s*==\s*['\"]on_chat_model_stream['\"][\s\S]+?continue",
        src,
    )
    assert stream_match, "未找到 on_chat_model_stream 处理分支"
    body = stream_match.group(0)
    assert "parser.feed" in body, "必须用 parser.feed 实时处理 chunk"
    assert "send_json" in body, "必须实时 send_json emit"
    assert "full_response +=" not in body, "禁止 full_response += content 缓存模式(会导致转圈 bug 回潮)"


def test_settings_view_reads_models_from_store() -> None:
    """SettingsView 必须从 useStore.models 读,不能维护 local useState。

    WHY:旧实现 useState<Model[]>([]) + useEffect([]) 只拉一次,
    ModelConfigModal 切完调 setModels 写进 store,SettingsView 的 local
    state 不动,「共配置 N 个模型」永远停在初值。修复:直接从 store 读,
    自动 re-render。
    """
    settings = (REPO_ROOT / "frontend/src/components/desktop/SettingsView.tsx").read_text(encoding="utf-8")

    # 1) 必须从 useStore 读 models(不能 useState)
    assert "useStore" in settings, "SettingsView 必须 import useStore"
    assert re.search(
        r"useStore\(\s*\(\s*\w+\s*\)\s*=>\s*\w+\.models\s*\)",
        settings,
    ), "SettingsView 必须用 useStore((s) => s.models) 读 models"
    assert "useState<Model[]>" not in settings, (
        "SettingsView 不能用 useState<Model[]>([]) 维护 local models,否则 ModelConfigModal 切完不会触发它 re-render"
    )
    # 2) 不应再有自己的 loadModels effect
    assert "useEffect" not in settings or "apiFetch('/api/models')" not in settings, (
        "SettingsView 不应再 useEffect 拉 /api/models — 由 ModelConfigModal 维护 store.models 即可"
    )
