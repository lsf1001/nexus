"""桌面 APP 启动入口。

策略:
- uvicorn 跑在后台 daemon 线程(子线程不能 await,故起独立事件循环)
- pywebview 在主线程弹 WKWebView 窗口,指向 http://127.0.0.1:30000/app/
- 前端静态文件由 FastAPI 自身在 /app 挂载服务,无需另开端口

与开发模式 `python nexus/backend/run.py` 的区别:后者直接前台跑 uvicorn,
浏览器开 http://localhost:30000/app/。本入口是给打包后的 .app(DMG)用。
"""

import argparse
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


def main() -> int:
    """APP 入口:起后端 + 弹原生窗口。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=30000)
    parser.add_argument("--no-gui", action="store_true", help="只跑后端不开窗口(headless / debug)")
    args = parser.parse_args()

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

    webview.create_window(
        title="Nexus",
        url=f"http://{args.host}:{args.port}/app/",
        width=1280,
        height=820,
        min_size=(900, 600),
        text_select=True,
    )
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
