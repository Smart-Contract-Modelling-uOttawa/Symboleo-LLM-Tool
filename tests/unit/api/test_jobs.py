from datetime import datetime, timedelta

from symboleo_llm_tool.api.jobs import TTL, cleanup_expired, create_job, get_job


def test_cleanup_expired_removes_old_completed_jobs() -> None:
    create_job("old")
    job = get_job("old")
    job.completed_at = datetime.now() - TTL - timedelta(seconds=1)  # type: ignore[union-attr]
    cleanup_expired()
    assert get_job("old") is None


def test_cleanup_expired_keeps_recent_completed_jobs() -> None:
    create_job("recent")
    job = get_job("recent")
    job.completed_at = datetime.now()  # type: ignore[union-attr]
    cleanup_expired()
    assert get_job("recent") is not None


def test_cleanup_expired_keeps_incomplete_jobs() -> None:
    create_job("running")
    cleanup_expired()
    assert get_job("running") is not None
