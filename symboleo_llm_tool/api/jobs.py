import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Generic, TypeVar

from symboleo_llm_tool.output.models import PipelineResult, SuiteResult

TTL = timedelta(minutes=5)

T = TypeVar("T")


@dataclass
class Job(Generic[T]):
    run_id: str
    queue: asyncio.Queue  # type: ignore[type-arg]
    task: "asyncio.Task[None] | None" = field(default=None)
    result: T | None = field(default=None)
    error: str | None = field(default=None)
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = field(default=None)

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None


# Single store for both run and suite jobs — they share TTL cleanup and uuids
# never collide. The typed accessors below carry the result type to call sites.
_store: dict[str, Job[Any]] = {}


def create_job(run_id: str) -> Job[PipelineResult]:
    job: Job[PipelineResult] = Job(run_id=run_id, queue=asyncio.Queue())
    _store[run_id] = job
    return job


def create_suite_job(run_id: str) -> Job[SuiteResult]:
    job: Job[SuiteResult] = Job(run_id=run_id, queue=asyncio.Queue())
    _store[run_id] = job
    return job


def get_job(run_id: str) -> Job[PipelineResult] | None:
    return _store.get(run_id)


def get_suite_job(run_id: str) -> Job[SuiteResult] | None:
    return _store.get(run_id)


def cleanup_expired() -> None:
    now = datetime.now()
    expired = [
        run_id
        for run_id, job in _store.items()
        if job.completed_at is not None and now - job.completed_at > TTL
    ]
    for run_id in expired:
        del _store[run_id]


def reset_store() -> None:
    _store.clear()
