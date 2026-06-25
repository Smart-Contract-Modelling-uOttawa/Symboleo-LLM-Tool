"""Cooperative cancellation + the coordinator bundle for concurrent suite runs.

Domain-agnostic primitives shared by the pipeline (candidate concurrency) and the
suite runner (experiment concurrency). See ``docs/suite-concurrency-design.md``.

Cancellation is *cooperative*: it cannot interrupt an in-flight LLM call or JAR
subprocess. Workers check ``CancellationToken.cancelled`` at safe checkpoints
(before a candidate starts, between correction iterations) and stop there.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass


class CancellationToken:
    """A cooperative cancellation flag. A child is cancelled if it OR an ancestor is.

    Linking lets one request-scoped token (cancelled on, e.g., a fatal error or a
    dropped connection) sit above per-experiment tokens (cancelled on that
    experiment's first convergence) — a worker checks only its own token and
    transparently inherits cancellation from above.
    """

    def __init__(self, parent: CancellationToken | None = None) -> None:
        self._event = threading.Event()
        self._parent = parent

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        if self._event.is_set():
            return True
        return self._parent is not None and self._parent.cancelled

    def child(self) -> CancellationToken:
        """A token cancelled when itself or this (its parent) is cancelled."""
        return CancellationToken(parent=self)


@dataclass(frozen=True)
class RunCoordinator:
    """What a *concurrent* ``pipeline.run`` needs: the shared work pool + cancel view.

    Passed only when running concurrently; its absence is what selects the
    unchanged sequential path. The pool is shared across all experiments in a
    suite so a single ``max_workers`` bounds concurrent candidates globally.
    """

    candidate_pool: ThreadPoolExecutor
    cancel: CancellationToken
