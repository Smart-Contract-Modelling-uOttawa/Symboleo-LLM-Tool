from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from symboleo_llm_tool.api.jobs import reset_store
from symboleo_llm_tool.api.routes import init_router, reset_router, router

TEST_UI_CONFIG: dict[str, Any] = {
    "models": {
        "openai": ["gpt-4o-mini"],
        "anthropic": ["claude-haiku-4-5"],
    },
    "parameters": {},
}


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None, None, None]:
    init_router(TEST_UI_CONFIG)
    reset_store()
    yield
    reset_router()
    reset_store()


@pytest.fixture
def patch_run_pipeline() -> Generator[None, None, None]:
    with patch("symboleo_llm_tool.api.routes._run_pipeline", new_callable=AsyncMock):
        yield


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)
