import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from symboleo_llm_tool.output.models import PipelineResult

TTL = timedelta(minutes=5)


@dataclass
class Job:
    run_id: str
    queue: asyncio.Queue  # type: ignore[type-arg]
    task: "asyncio.Task[None] | None" = field(default=None)
    result: PipelineResult | None = field(default=None)
    error: str | None = field(default=None)
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = field(default=None)

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None


_store: dict[str, Job] = {}


def create_job(run_id: str) -> Job:
    job = Job(run_id=run_id, queue=asyncio.Queue())
    _store[run_id] = job
    return job


def get_job(run_id: str) -> Job | None:
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
