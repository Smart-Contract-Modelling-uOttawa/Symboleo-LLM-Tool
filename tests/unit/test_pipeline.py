from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from symboleo_llm_tool.concurrency import CancellationToken, RunCoordinator
from symboleo_llm_tool.config.models import (
    LLMConfig,
    PipelineConfig,
    RunConfig,
    StageConfig,
)
from symboleo_llm_tool.pipeline import pipeline
from tests.helpers import make_generation, make_issue, make_usage


def _make_config(**pipeline_kwargs: Any) -> PipelineConfig:
    stage = StageConfig(
        llm=LLMConfig(provider="anthropic", model="claude-haiku-4-5"),
        strategy="zero_shot",
    )
    return PipelineConfig(
        pipeline=RunConfig(**pipeline_kwargs),
        generation=stage,
        correction=stage,
    )


@pytest.fixture(autouse=True)
def mock_deps():
    with (
        patch("shutil.which", return_value="/usr/bin/java"),
        patch("symboleo_llm_tool.pipeline.pipeline.SymboleoWrapper") as mock_wrapper_cls,
        patch("symboleo_llm_tool.pipeline.pipeline.create_adapter") as mock_llm_cls,
        patch("symboleo_llm_tool.pipeline.pipeline.get_strategy") as mock_get_strategy,
        patch("symboleo_llm_tool.pipeline.pipeline._load_grammar", return_value=""),
    ):
        mock_wrapper = MagicMock()
        mock_wrapper_cls.return_value = mock_wrapper

        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        mock_strategy = MagicMock()
        mock_strategy.build_generation_prompt.return_value = "gen prompt"
        mock_strategy.build_correction_prompt.return_value = "corr prompt"
        mock_get_strategy.return_value = mock_strategy

        yield mock_wrapper, mock_llm, mock_strategy


def test_converges_immediately_when_no_errors(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("valid symboleo")
    mock_wrapper.validate.return_value = []

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    assert result.success is True
    assert result.candidates[0].converged is True
    assert result.candidates[0].iterations_used == 0
    assert mock_llm.generate.call_count == 1


def test_stops_at_max_iterations_when_always_errors(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("invalid")
    mock_wrapper.validate.return_value = [make_issue()]

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    assert result.success is False
    assert result.candidates[0].converged is False
    assert result.candidates[0].iterations_used == 3


def test_error_history_length_matches_iterations(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("invalid")
    mock_wrapper.validate.return_value = [make_issue()]

    result = pipeline.run("contract text", _make_config(max_iterations=2))

    # iteration 0 (generation) + iterations 1 and 2 (correction)
    assert len(result.candidates[0].error_history) == 3


def test_stop_on_first_convergence_halts_remaining_candidates(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("valid")
    mock_wrapper.validate.return_value = []

    result = pipeline.run(
        "contract text",
        _make_config(num_candidates=3, stop_on_first_convergence=True),
    )

    assert len(result.candidates) == 1
    assert result.success is True


def test_all_candidates_run_when_stop_on_first_convergence_false(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("valid")
    mock_wrapper.validate.return_value = []

    result = pipeline.run(
        "contract text",
        _make_config(num_candidates=3, stop_on_first_convergence=False),
    )

    assert len(result.candidates) == 3


def test_on_progress_called_after_generation(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("valid")
    mock_wrapper.validate.return_value = []

    progress = MagicMock()
    pipeline.run("contract text", _make_config(max_iterations=3), on_progress=progress)

    progress.assert_called_once_with(0, 0, [], 1, 3)


def test_on_progress_called_after_each_correction(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("invalid")
    error = make_issue()
    mock_wrapper.validate.side_effect = [[error], [error], []]

    progress = MagicMock()
    pipeline.run("contract text", _make_config(max_iterations=3), on_progress=progress)

    assert progress.call_args_list == [
        call(0, 0, [error], 1, 3),
        call(0, 1, [error], 1, 3),
        call(0, 2, [], 1, 3),
    ]


def test_usage_recorded_on_each_iteration(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation(
        "invalid", usage=make_usage(prompt_tokens=30, completion_tokens=12, cost_usd=0.005)
    )
    mock_wrapper.validate.side_effect = [[make_issue()], []]

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    history = result.candidates[0].error_history
    # generation (iter 0) + one correction (iter 1), each carrying its call's usage
    assert len(history) == 2
    assert all(record.usage is not None for record in history)
    # total_tokens is computed: 30 + 12
    assert [record.usage.total_tokens for record in history] == [42, 42]
    assert [record.usage.cost_usd for record in history] == [0.005, 0.005]


def test_grammar_load_failure_propagates(mock_deps):
    with patch(
        "symboleo_llm_tool.pipeline.pipeline._load_grammar",
        side_effect=RuntimeError("Failed to load Symboleo grammar resource"),
    ):
        with pytest.raises(RuntimeError, match="Failed to load Symboleo grammar resource"):
            pipeline.run("contract text", _make_config())


def test_clean_response_strips_markdown_fences(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("```symboleo\nContract Test() {}\n```")
    mock_wrapper.validate.return_value = []

    result = pipeline.run("contract text", _make_config())

    assert result.candidates[0].final_code == "Contract Test() {}"


def test_clean_response_strips_plain_fences(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("```\nContract Test() {}\n```")
    mock_wrapper.validate.return_value = []

    result = pipeline.run("contract text", _make_config())

    assert result.candidates[0].final_code == "Contract Test() {}"


# --- Concurrent candidate execution (coordinator supplied) ---------------------


def test_coordinator_runs_all_candidates_and_reorders_them(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("valid")
    mock_wrapper.validate.return_value = []

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = pipeline.run(
            "contract text",
            _make_config(num_candidates=3, stop_on_first_convergence=False),
            coordinator=RunCoordinator(candidate_pool=pool, cancel=CancellationToken()),
        )

    assert result.success is True
    # futures finish out of order; candidates come back sorted by id
    assert [c.candidate_id for c in result.candidates] == [0, 1, 2]


def test_coordinator_skips_all_candidates_when_pre_cancelled(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("valid")
    mock_wrapper.validate.return_value = []

    cancel = CancellationToken()
    cancel.cancel()  # cancelled before any candidate starts
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = pipeline.run(
            "contract text",
            _make_config(num_candidates=3),
            coordinator=RunCoordinator(candidate_pool=pool, cancel=cancel),
        )

    assert result.candidates == []
    assert result.success is False


def test_coordinator_stop_on_first_convergence_cancels_siblings(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("valid")
    mock_wrapper.validate.return_value = []

    cancel = CancellationToken()
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = pipeline.run(
            "contract text",
            _make_config(num_candidates=3, stop_on_first_convergence=True),
            coordinator=RunCoordinator(candidate_pool=pool, cancel=cancel),
        )

    # The tripped token is the deterministic effect; how many in-flight candidates
    # finish before it lands is a race, so only the bounds are asserted.
    assert cancel.cancelled is True
    assert result.success is True
    assert 1 <= len(result.candidates) <= 3
    assert all(c.converged for c in result.candidates)


def test_coordinator_without_stop_on_first_convergence_leaves_token_untripped(mock_deps):
    # Negative control for the test above: without the flag no candidate cancels
    # its siblings, so all of them run.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("valid")
    mock_wrapper.validate.return_value = []

    cancel = CancellationToken()
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = pipeline.run(
            "contract text",
            _make_config(num_candidates=3, stop_on_first_convergence=False),
            coordinator=RunCoordinator(candidate_pool=pool, cancel=cancel),
        )

    assert cancel.cancelled is False
    assert len(result.candidates) == 3


def test_cancel_mid_run_stops_the_correction_loop(mock_deps):
    # The entry checkpoint is covered above; this is the between-iterations one,
    # which is what a Stop or disconnect actually hits during a long correction
    # loop. Tripping the token from the progress callback is deterministic.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("invalid")
    mock_wrapper.validate.return_value = [make_issue()]

    cancel = CancellationToken()

    def cancel_after_generation(candidate_id, iteration, errors, total_candidates, total_iters):
        cancel.cancel()

    result = pipeline.run(
        "contract text",
        _make_config(max_iterations=3),
        on_progress=cancel_after_generation,
        cancel=cancel,
    )

    # Generation recorded iteration 0, then the loop broke — without the
    # checkpoint all three correction iterations would run.
    candidate = result.candidates[0]
    assert candidate.iterations_used == 0
    assert len(candidate.error_history) == 1
    assert mock_llm.generate.call_count == 1


def test_coordinator_token_takes_precedence_over_a_bare_cancel(mock_deps):
    # run() documents that a coordinator's own token wins; every other test
    # supplies only one of the two, so the precedence itself was unverified.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("valid")
    mock_wrapper.validate.return_value = []

    already_cancelled = CancellationToken()
    already_cancelled.cancel()

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = pipeline.run(
            "contract text",
            _make_config(num_candidates=2),
            coordinator=RunCoordinator(candidate_pool=pool, cancel=CancellationToken()),
            cancel=already_cancelled,
        )

    # The live coordinator token governs, so the run proceeds despite the
    # pre-cancelled bare token.
    assert len(result.candidates) == 2


def test_cancel_token_skips_sequential_candidates(mock_deps):
    # The single-run cancel path (no coordinator): a tripped token aborts the
    # sequential run cooperatively — used by the API on client disconnect.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("valid")
    mock_wrapper.validate.return_value = []

    cancel = CancellationToken()
    cancel.cancel()
    result = pipeline.run("contract text", _make_config(num_candidates=2), cancel=cancel)

    assert result.candidates == []
    assert result.success is False


# --- Severity gating (ERROR blocks, WARNING does not) -------------------------


def test_warnings_only_do_not_block_convergence(mock_deps):
    # Warning-only is the discriminating fixture — a zero-issue one converges
    # under any severity rule.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("valid symboleo")
    mock_wrapper.validate.return_value = [make_issue(severity="WARNING")]

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    assert result.success is True
    assert result.candidates[0].converged is True
    assert result.candidates[0].iterations_used == 0
    assert mock_llm.generate.call_count == 1  # generation only — no correction
    history = result.candidates[0].error_history
    assert len(history) == 1
    assert history[0].errors[0].severity == "WARNING"


def test_correction_prompt_receives_only_blocking_errors(mock_deps):
    mock_wrapper, mock_llm, mock_strategy = mock_deps
    err = make_issue(severity="ERROR", message="bad token")
    warn = make_issue(severity="WARNING", message="unused declaration")
    mock_llm.generate.return_value = make_generation("code")
    mock_wrapper.validate.side_effect = [[err, warn], []]
    progress = MagicMock()

    result = pipeline.run("contract text", _make_config(max_iterations=3), on_progress=progress)

    corr_context = mock_strategy.build_correction_prompt.call_args.args[0]
    assert corr_context.errors == [err]  # warnings never reach the prompt
    assert result.candidates[0].error_history[0].errors == [err, warn]
    assert progress.call_args_list[0] == call(0, 0, [err, warn], 1, 3)  # callback gets ALL issues


def test_convergence_with_residual_warnings_records_them(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    err = make_issue(severity="ERROR")
    warn = make_issue(severity="WARNING")
    mock_llm.generate.return_value = make_generation("code")
    mock_wrapper.validate.side_effect = [[err], [warn]]
    progress = MagicMock()

    result = pipeline.run("contract text", _make_config(max_iterations=3), on_progress=progress)

    candidate = result.candidates[0]
    assert candidate.converged is True
    assert candidate.iterations_used == 1
    assert candidate.error_history[1].errors == [warn]
    # The correction-stage callback carries warnings too — filtering here would
    # silently drop them from the CLI and suite progress lines.
    assert progress.call_args_list[1] == call(0, 1, [warn], 1, 3)
