import threading
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from symboleo_llm_tool.concurrency import CancellationToken
from symboleo_llm_tool.config.models import (
    Experiment,
    LLMConfig,
    PipelineConfig,
    StageConfig,
    SuiteConfig,
)
from symboleo_llm_tool.experiments import runner
from symboleo_llm_tool.output.models import PipelineResult
from tests.helpers import make_issue


def _stage(strategy: str = "zero_shot") -> StageConfig:
    return StageConfig(llm=LLMConfig(provider="openai", model="gpt-4o-mini"), strategy=strategy)


def _config(strategy: str = "zero_shot") -> PipelineConfig:
    return PipelineConfig(generation=_stage(strategy), correction=_stage(strategy))


def _suite(*strategies: str, max_concurrency: int = 1) -> SuiteConfig:
    # Defaults to 1 (sequential) so the composition-contract tests below are
    # deterministic; the concurrent path is covered explicitly with K=2.
    return SuiteConfig(
        contract_text="contract text",
        max_concurrency=max_concurrency,
        experiments=[
            Experiment(name=f"exp_{i}", config=_config(s)) for i, s in enumerate(strategies)
        ],
    )


def _result() -> PipelineResult:
    return PipelineResult(
        success=True,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        input_file="",
        candidates=[],
    )


def test_runs_each_experiment_and_preserves_names_and_order() -> None:
    with patch("symboleo_llm_tool.pipeline.run", return_value=_result()) as mock_run:
        suite_result = runner.run_suite(_suite("zero_shot", "cot", "few_shot"))

    assert [e.name for e in suite_result.experiments] == ["exp_0", "exp_1", "exp_2"]
    assert mock_run.call_count == 3


def test_calls_pipeline_run_with_contract_and_each_config() -> None:
    suite = _suite("zero_shot", "cot")
    with patch("symboleo_llm_tool.pipeline.run", return_value=_result()) as mock_run:
        runner.run_suite(suite, input_file="meatsale.txt")

    for call_obj, experiment in zip(mock_run.call_args_list, suite.experiments):
        contract_text, config = call_obj.args
        assert contract_text == "contract text"
        assert config is experiment.config
        assert call_obj.kwargs["input_file"] == "meatsale.txt"


def test_forwards_progress_with_experiment_index_prepended() -> None:
    error = make_issue()

    def fake_run(contract_text, config, input_file="", on_progress=None, cancel=None):
        if on_progress is not None:
            # pipeline-level args: candidate_id, iteration, errors, totals
            on_progress(0, 1, [error], 2, 3)
        return _result()

    suite_progress = MagicMock()
    with patch("symboleo_llm_tool.pipeline.run", side_effect=fake_run):
        runner.run_suite(_suite("zero_shot", "cot"), on_progress=suite_progress)

    assert suite_progress.call_args_list == [
        ((0, 0, 1, [error], 2, 3),),  # experiment 0 prepended
        ((1, 0, 1, [error], 2, 3),),  # experiment 1 prepended
    ]


def test_no_progress_callback_passes_none_to_pipeline() -> None:
    with patch("symboleo_llm_tool.pipeline.run", return_value=_result()) as mock_run:
        runner.run_suite(_suite("zero_shot"))

    assert mock_run.call_args.kwargs["on_progress"] is None


# --- Concurrent path (max_concurrency > 1) -------------------------------------


def test_concurrent_runs_all_experiments_preserving_order() -> None:
    with patch("symboleo_llm_tool.pipeline.run", return_value=_result()) as mock_run:
        suite_result = runner.run_suite(_suite("zero_shot", "cot", "few_shot", max_concurrency=2))

    # Results are reordered back into experiment order even though futures finish
    # out of order.
    assert [e.name for e in suite_result.experiments] == ["exp_0", "exp_1", "exp_2"]
    assert mock_run.call_count == 3


def test_concurrent_forwards_progress_for_every_experiment() -> None:
    error = make_issue()

    def fake_run(contract_text, config, input_file="", on_progress=None, coordinator=None):
        if on_progress is not None:
            on_progress(0, 1, [error], 2, 3)
        return _result()

    received: list[tuple] = []
    lock = threading.Lock()

    def record(*args: object) -> None:
        with lock:
            received.append(args)

    with patch("symboleo_llm_tool.pipeline.run", side_effect=fake_run):
        runner.run_suite(_suite("zero_shot", "cot", max_concurrency=2), on_progress=record)

    # Order is non-deterministic under concurrency; key by experiment_index.
    assert sorted(received, key=lambda a: a[0]) == [
        (0, 0, 1, [error], 2, 3),
        (1, 0, 1, [error], 2, 3),
    ]


def test_concurrent_fails_fast_and_propagates_on_exception() -> None:
    # Fail-fast has two halves: the error propagates, *and* the request token is
    # tripped so sibling experiments short-circuit instead of burning tokens.
    token = CancellationToken()

    def fake_run(contract_text, config, input_file="", on_progress=None, coordinator=None):
        if config.generation.strategy == "cot":
            raise RuntimeError("boom")
        return _result()

    with patch("symboleo_llm_tool.pipeline.run", side_effect=fake_run):
        with pytest.raises(RuntimeError, match="boom"):
            runner.run_suite(
                _suite("zero_shot", "cot", "few_shot", max_concurrency=2), cancel=token
            )

    assert token.cancelled is True


def test_max_concurrency_is_clamped() -> None:
    assert _suite("zero_shot", max_concurrency=64).max_concurrency == 8
    assert _suite("zero_shot", max_concurrency=0).max_concurrency == 1


def test_sequential_suite_forwards_cancel_to_pipeline() -> None:
    # The K=1 path must thread the request-scoped token through to pipeline.run so
    # a disconnect or explicit cancel can abort it.
    token = CancellationToken()
    captured: dict[str, object] = {}

    def fake_run(contract_text, config, input_file="", on_progress=None, cancel=None):
        captured["cancel"] = cancel
        return _result()

    with patch("symboleo_llm_tool.pipeline.run", side_effect=fake_run):
        runner.run_suite(_suite("zero_shot", max_concurrency=1), cancel=token)

    assert captured["cancel"] is token


def test_empty_suite_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one experiment"):
        SuiteConfig(contract_text="x", experiments=[])


def test_duplicate_experiment_names_are_rejected() -> None:
    with pytest.raises(ValidationError, match="names must be unique"):
        SuiteConfig(
            contract_text="x",
            experiments=[
                Experiment(name="dup", config=_config()),
                Experiment(name="dup", config=_config()),
            ],
        )
