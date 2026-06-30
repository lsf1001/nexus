"""桌面 APP 启动入口。

策略:
- uvicorn 跑在后台 daemon 线程(子线程不能 await,故起独立事件循环)
- pywebview 在主线程弹 WKWebView 窗口,指向 http://127.0.0.1:30000/app/
- 前端静态文件由 FastAPI 自身在 /app 挂载服务,无需另开端口

macOS 关窗行为:
- 点 X → 窗口隐藏(进程保活,Dock 点击重开)
- cmd+Q / 菜单 Quit → 正常退出
- 实现:monkey-patch WindowDelegate.windowShouldClose_ 调用 pywebview window.hide()
  (pywebview 的 closing 事件返回值被 Event.set() 异步吃掉了,不能依赖)
"""

import argparse
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# 确保项目根目录在 sys.path(同 run.py)
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _wait_for_backend(url: str, *, timeout: float = 30.0, interval: float = 0.2) -> bool:
    """轮询 /health,直到返回 200 或超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:  # noqa: S310 - 本机端口
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(interval)
    return False


def _run_backend(host: str, port: int) -> None:
    """在子线程跑 uvicorn,阻塞到 shutdown。"""
    import uvicorn

    from nexus.backend.main import app

    uvicorn.run(app, host=host, port=port, log_level="info")


def _patch_cocoa_close_behavior() -> None:
    """monkey-patch pywebview cocoa 关闭行为,符合 macOS APP 习惯。

    pywebview 6.x 的 Event.set() 在子线程跑 handler 但同步读返回值,return 永远拿不到,
    closing 事件返回 True 无法阻止关闭。直接替换底层方法:

    1. WindowDelegate.windowShouldClose_ → 点 X 时 hide + 返回 False
    2. AppDelegate.applicationShouldHandleReopen_hasVisibleWindows_ → Dock 点击重开窗口

    cmd+Q 走 applicationShouldTerminate_,不影响,正常退出。
    """
    try:
        from webview.platforms import cocoa as _cocoa
    except ImportError:
        return  # 非 macOS 平台,无 patch

    _BrowserView = _cocoa.BrowserView  # noqa: N806 - macOS Cocoa API 命名固定

    def _patched_windowShouldClose_(self, window):  # noqa: ANN001, N802 - NSWindowDelegate 签名固定
        """点 X 时:隐藏窗口不销毁,返回 NO 阻止关闭。"""
        instance = _BrowserView.get_instance("window", window)
        if instance is not None:
            try:
                instance.pywebview_window.hide()
            except Exception:  # noqa: BLE001 - 容错
                pass
        return False  # Foundation.NO - 不要让 NSWindow 关闭

    def _patched_applicationShouldHandleReopen_hasVisibleWindows_(self, app, flag):  # noqa: ANN001, N802 - NSApplicationDelegate 签名固定
        """Dock 点击图标:重新显示被隐藏的窗口。"""
        try:
            import webview

            for win in webview.windows:
                win.show()
            app.activateIgnoringOtherApps_(True)
        except Exception:  # noqa: BLE001
            pass
        return True

    # 替换方法。pywebview 用嵌套类,直接覆盖即可对所有实例生效。
    _BrowserView.WindowDelegate.windowShouldClose_ = _patched_windowShouldClose_
    _BrowserView.AppDelegate.applicationShouldHandleReopen_hasVisibleWindows_ = (
        _patched_applicationShouldHandleReopen_hasVisibleWindows_
    )


def _patch_titlebar() -> None:
    """让标题栏透明,让 sidebar 直接延伸到窗口顶部,避免 Dark Mode 下"黑色横条"违和。

    pywebview 没暴露 titlebarAppearsTransparent,直接通过 NSWindow API 设置。
    必须在主线程调(NSWindow geometry 只允许主线程),所以用 AppHelper.callAfter 派发。
    同时强制 NSApp 用 Aqua(Light)外观,标题栏和 chrome 不再跟随系统 Dark Mode。
    """
    from PyObjCTools import AppHelper

    def _do():
        try:
            from AppKit import NSApp, NSAppearance
            from webview.platforms import cocoa as _cocoa

            # 强制整个 APP 用 Light 外观 → 标题栏/红绿灯/系统 chrome 都是浅色,
            # 避免 macOS Dark Mode 下的"黑色横条"违和感。
            aqua = NSAppearance.appearanceNamed_("NSAppearanceNameAqua")
            NSApp.setAppearance_(aqua)
            for browser in _cocoa.BrowserView.instances.values():
                ns_window = browser.window
                if ns_window is None:
                    continue
                # 标题栏透明(让 sidebar 背景穿透到 traffic lights 下方)
                ns_window.setTitlebarAppearsTransparent_(True)
                ns_window.setTitleVisibility_(1)  # NSWindowTitleHidden = 1
        except Exception as exc:  # noqa: BLE001
            print(f"[launcher] titlebar patch failed: {exc}", file=sys.stderr)

    AppHelper.callAfter(_do)


def _activate_app() -> None:
    """Dock 点击时把窗口带到前台。"""
    try:
        from AppKit import NSApp

        NSApp.activateIgnoringOtherApps_(True)
    except Exception:  # noqa: BLE001 - 容错
        pass


def _on_shown(window) -> None:  # noqa: ANN001 - pywebview event 签名
    """窗口显示时激活到前台。"""
    _activate_app()


def main() -> int:
    """APP 入口:起后端 + 弹原生窗口。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=30000)
    parser.add_argument("--no-gui", action="store_true", help="只跑后端不开窗口(headless / debug)")
    args = parser.parse_args()

    # PyInstaller 打包后,告诉后端前端 dist 在哪。
    # PyInstaller 6.20 + --osx-bundle-identifier 把 _MEIPASS 设在 Contents/Frameworks/,
    # 前端 dist 在 Contents/Resources/frontend,所以固定走 fallback。
    # dev 模式下走 main.py 里的"项目目录/frontend/dist"分支,无需设。
    if getattr(sys, "frozen", False) and not os.environ.get("NEXUS_FRONTEND_DIST"):
        bundled_frontend = Path(sys._MEIPASS) / "frontend"  # type: ignore[attr-defined]
        if not bundled_frontend.exists():
            bundled_frontend = Path(sys._MEIPASS).parent / "Resources" / "frontend"
        if bundled_frontend.exists():
            os.environ["NEXUS_FRONTEND_DIST"] = str(bundled_frontend)

    # 在 import webview / create_window 之前 patch 关窗行为
    _patch_cocoa_close_behavior()

    backend_thread = threading.Thread(
        target=_run_backend,
        args=(args.host, args.port),
        daemon=True,
        name="nexus-backend",
    )
    backend_thread.start()

    health_url = f"http://{args.host}:{args.port}/health"
    if not _wait_for_backend(health_url, timeout=30.0):
        print(f"backend failed to start within 30s at {health_url}", file=sys.stderr)
        return 1

    if args.no_gui:
        # headless 模式:后端跑着,主线程阻塞,直到 Ctrl+C
        try:
            backend_thread.join()
        except KeyboardInterrupt:
            pass
        return 0

    # 起原生 WKWebView 窗口
    import webview

    window = webview.create_window(
        title="Nexus",
        url=f"http://{args.host}:{args.port}/app/",
        width=1280,
        height=820,
        min_size=(900, 600),
        # 跟随系统外观:CSS 用 prefers-color-scheme,NSWindow 也用 system default
        # 这样 macOS Dark Mode 时标题栏和 body 都是深色,Light Mode 都是浅色,无违和
        text_select=True,
    )
    # 窗口显示时激活到前台(Dock 点击触发)
    window.events.shown += _on_shown
    # 窗口已挂载到 NSWindow 后,patch 标题栏让 sidebar 延伸到顶
    window.events.shown += lambda _w=None: _patch_titlebar()

    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
