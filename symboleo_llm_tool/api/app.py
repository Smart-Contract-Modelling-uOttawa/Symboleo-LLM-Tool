import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import yaml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from symboleo_llm_tool.api import routes
from symboleo_llm_tool.api.jobs import cleanup_expired
from symboleo_llm_tool.config.models import SymboleoConfig
from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    config_path = Path("configs/ui_config.yaml")
    if not config_path.exists():
        raise RuntimeError(f"UI config not found: {config_path.resolve()}")
    ui_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    routes.init_router(ui_config)

    # Fail fast if Java or JAR is missing — SymboleoWrapper.__init__ calls _preflight()
    symboleo_cfg = SymboleoConfig()
    SymboleoWrapper(symboleo_cfg.jar_path, symboleo_cfg.java_executable)

    cleanup_task = asyncio.create_task(_ttl_cleanup_loop())

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


async def _ttl_cleanup_loop() -> None:
    while True:
        await asyncio.sleep(60)
        cleanup_expired()


app = FastAPI(title="Symboleo LLM Tool API", version="0.1.0", lifespan=_lifespan)

_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router, prefix="/api")
