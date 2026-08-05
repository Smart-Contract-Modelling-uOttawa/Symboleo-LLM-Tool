import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Generic, TypeVar

from symboleo_llm_tool.concurrency import CancellationToken
from symboleo_llm_tool.output.models import PipelineResult, SuiteResult

TTL = timedelta(minutes=5)
# Fallback for *involuntary* drops (crash, dead network) where no explicit
# cancel arrives. Just long enough to ride out EventSource auto-reconnect (a few
# seconds); the voluntary case (Stop button / tab close) cancels immediately via
# the cancel endpoint, so this only needs to be reconnect-safe, not generous.
DETACH_GRACE = timedelta(seconds=10)

T = TypeVar("T")


@dataclass
class Job(Generic[T]):
    run_id: str
    queue: asyncio.Queue  # type: ignore[type-arg]
    task: "asyncio.Task[None] | None" = field(default=None)
    result: T | None = field(default=None)
    error: str | None = field(default=None)
    # Persistence outcome of a completed run (see CompleteEvent for semantics).
    # Stashed here because the reconnect branch of the stream rebuilds the
    # terminal event from the job — without these it would blank the fields.
    output_dir: str | None = field(default=None)
    write_error: str | None = field(default=None)
    # Request-scoped cancellation, tripped when the stream stays detached past the
    # grace window (see cancel_abandoned). The pipeline checks it cooperatively.
    cancel: CancellationToken = field(default_factory=CancellationToken)
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = field(default=None)
    # When the live stream last disconnected; None while attached or never
    # streamed. Reconnect clears it.
    detached_at: datetime | None = field(default=None)

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None

    def mark_attached(self) -> None:
        self.detached_at = None

    def mark_detached(self) -> None:
        self.detached_at = datetime.now()


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


def get_any_job(run_id: str) -> Job[Any] | None:
    """Look up a job regardless of result type — for cancellation, where only the
    shared ``cancel`` token matters."""
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


def cancel_abandoned() -> None:
    """Cancel in-flight jobs whose stream has stayed detached past the grace window.

    A transient drop reattaches (clearing ``detached_at``) well within the grace,
    so only a genuinely-gone client trips cancellation. Once cancelled, the job
    completes cooperatively and is removed by ``cleanup_expired`` after its TTL.
    """
    now = datetime.now()
    for job in _store.values():
        if (
            not job.is_complete
            and job.detached_at is not None
            and now - job.detached_at > DETACH_GRACE
        ):
            job.cancel.cancel()


def reset_store() -> None:
    _store.clear()
