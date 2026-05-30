import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import uvicorn

# 动态导入以避免模块路径问题
from nexus.backend.config import CONFIG

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    # CLI args override config; config overrides defaults
    host = args.host or CONFIG.get("server_host", "0.0.0.0")
    port = args.port or CONFIG.get("server_port", 30000)

    uvicorn.run(
        "nexus.backend.main:app",
        host=host,
        port=port,
        reload=False,
    )