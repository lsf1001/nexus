"""Sidecar 入口: 只跑 FastAPI/uvicorn,不开 webview。

打包时被 PyInstaller 打成 nexus-runtime 二进制(无 webview 依赖)。
Tauri 主进程 spawn 这个 sidecar,绑定 127.0.0.1:30000。

为什么独立于 launcher.py:
- launcher.py 引入 webview + pyobjc,打 sidecar 时这些都不能打包
- runtime_main.py 极简,只引 uvicorn + nexus.backend.main,PyInstaller 友好
"""

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=30000)
    args = parser.parse_args()

    # PyInstaller 打包后,前端 dist 在 .app/Contents/Resources/frontend/。
    # PyInstaller 6.20 把 _MEIPASS 设在 Contents/Frameworks/,回退到 Resources。
    if getattr(sys, "frozen", False) and not os.environ.get("NEXUS_FRONTEND_DIST"):
        bundled = Path(sys._MEIPASS) / "frontend"  # type: ignore[attr-defined]
        if not bundled.exists():
            bundled = Path(sys._MEIPASS).parent / "Resources" / "frontend"  # type: ignore[attr-defined]
        if bundled.exists():
            os.environ["NEXUS_FRONTEND_DIST"] = str(bundled)

    import uvicorn

    from nexus.backend.main import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())