from datetime import datetime, timedelta

from symboleo_llm_tool.api.jobs import (
    DETACH_GRACE,
    TTL,
    cancel_abandoned,
    cleanup_expired,
    create_job,
    get_job,
)


def test_cleanup_expired_removes_old_completed_jobs() -> None:
    create_job("old")
    job = get_job("old")
    assert job is not None
    job.completed_at = datetime.now() - TTL - timedelta(seconds=1)
    cleanup_expired()
    assert get_job("old") is None


def test_cleanup_expired_keeps_recent_completed_jobs() -> None:
    create_job("recent")
    job = get_job("recent")
    assert job is not None
    job.completed_at = datetime.now()
    cleanup_expired()
    assert get_job("recent") is not None


def test_cleanup_expired_keeps_incomplete_jobs() -> None:
    create_job("running")
    job = get_job("running")
    assert job is not None
    # Backdated past the TTL: a cleanup measuring age from *creation* rather than
    # completion would reap this live job mid-run.
    job.created_at = datetime.now() - TTL - timedelta(seconds=1)
    cleanup_expired()
    assert get_job("running") is not None


# --- detach / grace cancellation ----------------------------------------------


def _detached(run_id: str, ago: timedelta) -> None:
    job = get_job(run_id)
    assert job is not None
    job.detached_at = datetime.now() - ago


def test_mark_detached_then_attached_clears_it() -> None:
    create_job("j")
    job = get_job("j")
    assert job is not None
    assert job.detached_at is None
    job.mark_detached()
    assert job.detached_at is not None
    job.mark_attached()
    assert job.detached_at is None


def test_cancel_abandoned_cancels_long_detached_incomplete_job() -> None:
    create_job("gone")
    _detached("gone", DETACH_GRACE + timedelta(seconds=1))
    cancel_abandoned()
    job = get_job("gone")
    assert job is not None
    assert job.cancel.cancelled is True


def test_cancel_abandoned_ignores_recently_detached_job() -> None:
    create_job("blip")
    _detached("blip", timedelta(seconds=1))  # within grace (reconnect window)
    cancel_abandoned()
    job = get_job("blip")
    assert job is not None
    assert job.cancel.cancelled is False


def test_cancel_abandoned_ignores_attached_job() -> None:
    create_job("attached")  # detached_at is None
    job = get_job("attached")
    assert job is not None
    # Old enough to be cancelled if the grace were measured from creation instead
    # of the detach stamp — an attached job must survive regardless of its age.
    job.created_at = datetime.now() - DETACH_GRACE - timedelta(seconds=1)
    cancel_abandoned()
    assert job.cancel.cancelled is False


def test_cancel_abandoned_ignores_completed_job() -> None:
    create_job("done")
    _detached("done", DETACH_GRACE + timedelta(seconds=1))
    job = get_job("done")
    assert job is not None
    job.completed_at = datetime.now()
    cancel_abandoned()
    assert job.cancel.cancelled is False
