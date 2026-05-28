import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import uvicorn

if __name__ == "__main__":
    # 动态导入以避免模块路径问题
    from nexus.backend.config import CONFIG

    uvicorn.run(
        "nexus.backend.main:app",
        host=CONFIG.get("server_host", "0.0.0.0"),
        port=CONFIG.get("server_port", 30000),
        reload=False,  # 禁用热重载，避免进程管理混乱
    )