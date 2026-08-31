import os
import uvicorn

host = os.getenv("HOST", "0.0.0.0")
port = int(os.getenv("PORT", "8000"))
workers = int(os.getenv("WORKERS", "1"))
log_level = os.getenv("LOG_LEVEL", "info").lower()

uvicorn.run(
    "backend.main:app",
    host=host,
    port=port,
    workers=workers,
    log_level=log_level,
)
