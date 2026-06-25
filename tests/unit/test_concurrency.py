from symboleo_llm_tool.concurrency import CancellationToken


def test_uncancelled_by_default() -> None:
    assert CancellationToken().cancelled is False


def test_cancel_sets_cancelled() -> None:
    token = CancellationToken()
    token.cancel()
    assert token.cancelled is True


def test_child_is_cancelled_when_parent_is() -> None:
    parent = CancellationToken()
    child = parent.child()
    assert child.cancelled is False
    parent.cancel()
    assert child.cancelled is True


def test_child_cancel_does_not_affect_parent() -> None:
    parent = CancellationToken()
    child = parent.child()
    child.cancel()
    assert child.cancelled is True
    assert parent.cancelled is False


def test_siblings_are_independent() -> None:
    parent = CancellationToken()
    first = parent.child()
    second = parent.child()
    first.cancel()
    assert first.cancelled is True
    assert second.cancelled is False
