import uvicorn
from nexus.backend.config import CONFIG

if __name__ == "__main__":
    uvicorn.run(
        "nexus.backend.main:app",
        host=CONFIG["server_host"],
        port=CONFIG["server_port"],
        reload=True,
        reload_dirs=["/Users/yxb/projects/nexus/nexus/backend"],
    )