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
from symboleo_llm_tool.llm.base import LLMCallError
from symboleo_llm_tool.pipeline import pipeline
from symboleo_llm_tool.symboleo.wrapper import ValidationCallError
from tests.helpers import make_generation, make_issue, make_usage

# A stand-in for "the model returned a contract". Corrections are adopted only
# when the response carries a `Domain`..`endContract` span, so a bare marker
# string means "the model returned no contract at all" — a different scenario,
# exercised deliberately by the rejection tests at the end of this file.
_CODE = "Domain D\nendDomain\nContract C ()\nendContract"


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
        patch("symboleo_llm_tool.pipeline.pipeline.load_grammar", return_value=""),
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
    mock_llm.generate.return_value = make_generation(_CODE)
    mock_wrapper.validate.return_value = [make_issue()]

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    assert result.success is False
    assert result.candidates[0].converged is False
    assert result.candidates[0].iterations_used == 3


def test_error_history_length_matches_iterations(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation(_CODE)
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
    mock_llm.generate.return_value = make_generation(_CODE)
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
        _CODE, usage=make_usage(prompt_tokens=30, completion_tokens=12, cost_usd=0.005)
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
        "symboleo_llm_tool.pipeline.pipeline.load_grammar",
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


# --- _clean_response: prose/fence extraction (direct function tests) -----------

_CONTRACT = (
    "Domain D\n  Seller isA Role with name: String;\nendDomain\n\n"
    "Contract C (a: Seller, b: Seller)\nObligations\n  o1: O(a, b, true, true);\nendContract"
)


def test_clean_response_extracts_contract_behind_prose_preamble():
    # The observed run_20260729_130405 failure shape: prose, then a fence. The
    # old fence-stripping only fired when the fence was the FIRST line, so the
    # parser died on English at line 1 and masked every real error below it.
    response = (
        "Here is the corrected SymboleoAC contract based on the provided "
        f"instructions and errors:\n\n```symboleo\n{_CONTRACT}\n```"
    )
    assert pipeline._clean_response(response) == _CONTRACT


def test_clean_response_drops_trailing_prose_after_fence():
    response = f"```symboleo\n{_CONTRACT}\n```\n\nLet me know if you need further corrections."
    assert pipeline._clean_response(response) == _CONTRACT


def test_clean_response_extracts_span_without_any_fences():
    response = f"Sure! The corrected contract:\n\n{_CONTRACT}\n\nAll errors are now fixed."
    assert pipeline._clean_response(response) == _CONTRACT


def test_clean_response_handles_unclosed_fence():
    response = f"Here is the contract:\n```symboleo\n{_CONTRACT}"
    assert pipeline._clean_response(response) == _CONTRACT


def test_clean_response_keeps_truncated_contract_to_end():
    # No endContract (max_tokens truncation): keep from Domain to the end so
    # the validator reports the truncation, rather than dropping everything.
    truncated = "Domain D\n  Seller isA Role;\nendDomain\nContract C (a: Seller, b: Seller)"
    response = f"Here is the contract:\n{truncated}"
    assert pipeline._clean_response(response) == truncated


def test_clean_response_passes_through_unrecognizable_content():
    # No Domain line anywhere: return it (fence-stripped) for the validator to
    # report as-is - inventing a span here would hide the malformation.
    assert pipeline._clean_response("I cannot produce a contract for this input.") == (
        "I cannot produce a contract for this input."
    )


def test_clean_response_leaves_clean_output_untouched():
    assert pipeline._clean_response(_CONTRACT) == _CONTRACT


# --- _has_contract_span: the correction-adoption gate --------------------------


def test_has_contract_span_accepts_a_truncated_contract():
    # No endContract (max_tokens truncation). Adoptable on purpose: the anchor is
    # the Domain line alone, so the validator gets to report the truncation
    # rather than the loop silently discarding a real contract.
    assert pipeline._has_contract_span("Domain D\n  Seller isA Role;") is True


def test_has_contract_span_rejects_prose():
    assert pipeline._has_contract_span("I cannot produce a contract for this input.") is False


@pytest.mark.parametrize(
    ("response", "has_span"),
    [
        (f"Here is the corrected contract:\n\n```symboleo\n{_CONTRACT}\n```", True),
        (f"```symboleo\n{_CONTRACT}\n```\n\nLet me know if you need more.", True),
        (f"Sure! The corrected contract:\n\n{_CONTRACT}\n\nAll errors are now fixed.", True),
        ("Domain D\n  Seller isA Role;\nendDomain", True),
        ("I cannot produce a contract for this input.", False),
        ("", False),
    ],
)
def test_has_contract_span_agrees_with_clean_response_extraction(response, has_span):
    # The gate reads _clean_response's OUTPUT rather than taking a flag from it,
    # so the two could in principle disagree. They must not: a span found during
    # extraction is a span present in the result, and vice versa.
    assert pipeline._has_contract_span(pipeline._clean_response(response)) is has_span


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
    mock_llm.generate.return_value = make_generation(_CODE)
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
    mock_llm.generate.return_value = make_generation(_CODE)
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
    mock_llm.generate.return_value = make_generation(_CODE)
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


# --- Contract-less correction responses are refused, not adopted ---------------


def test_rejects_correction_without_a_contract_and_keeps_previous_code(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.side_effect = [
        make_generation(_CODE),
        make_generation("I cannot fix this."),
    ]
    mock_wrapper.validate.side_effect = [[make_issue()]]

    result = pipeline.run("contract text", _make_config(max_iterations=1))

    candidate = result.candidates[0]
    assert candidate.final_code == _CODE  # not the refusal
    assert candidate.converged is False
    # The retained code is byte-identical, so a second JAR run would be pure waste.
    assert mock_wrapper.validate.call_count == 1


def test_rejected_iteration_is_recorded_with_its_response_and_usage(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    refusal = "```\nI cannot fix this.\n```"
    mock_llm.generate.side_effect = [make_generation(_CODE), make_generation(refusal)]
    mock_wrapper.validate.side_effect = [[make_issue()]]

    result = pipeline.run("contract text", _make_config(max_iterations=1))

    history = result.candidates[0].error_history
    # The RAW response, fences intact — the field is forensic, and storing the
    # cleaned text would hide a _clean_response bug at the one point it matters.
    assert history[1].rejected_response == refusal
    assert history[1].code == history[0].code
    assert history[1].errors == history[0].errors
    assert history[1].usage is not None
    assert history[0].rejected_response is None


def test_rejected_iteration_counts_toward_iterations_used_and_tokens(mock_deps):
    # The refused call was still made and still billed; dropping its record would
    # delete those tokens from every rollup that walks error_history.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.side_effect = [
        make_generation(_CODE, usage=make_usage(prompt_tokens=30, completion_tokens=12)),
        make_generation("nope", usage=make_usage(prompt_tokens=40, completion_tokens=3)),
    ]
    mock_wrapper.validate.side_effect = [[make_issue()]]

    result = pipeline.run("contract text", _make_config(max_iterations=1))

    candidate = result.candidates[0]
    assert candidate.iterations_used == 1
    assert candidate.total_tokens == 42 + 43


def test_rejected_final_iteration_keeps_the_retained_warning_count(mock_deps):
    # final_warning_count reads error_history[-1].errors, so recording an empty
    # list on a rejection would understate the retained code's warnings — and
    # make the record read as converged to anything inspecting it directly.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.side_effect = [make_generation(_CODE), make_generation("nope")]
    mock_wrapper.validate.side_effect = [[make_issue(), make_issue(severity="WARNING")]]

    result = pipeline.run("contract text", _make_config(max_iterations=1))

    assert result.candidates[0].final_warning_count == 1


def test_retries_after_a_rejection_from_the_retained_code(mock_deps):
    mock_wrapper, mock_llm, mock_strategy = mock_deps
    fixed = _CODE.replace("Contract C ()", "Contract C (a: Seller)")
    mock_llm.generate.side_effect = [
        make_generation(_CODE),
        make_generation("nope"),
        make_generation(fixed),
    ]
    mock_wrapper.validate.side_effect = [[make_issue()], []]

    result = pipeline.run("contract text", _make_config(max_iterations=2))

    # The retry is built from the retained code, never from the refused response.
    assert mock_strategy.build_correction_prompt.call_args_list[1].args[0].current_code == _CODE
    candidate = result.candidates[0]
    assert candidate.converged is True
    assert candidate.final_code == fixed


def test_generation_without_a_contract_is_adopted_and_reported(mock_deps):
    # Negative control: the gate is correction-only. At iteration 0 there is no
    # previous code to protect, so garbage is adopted and reported as a failure.
    # Gating here would instead require an empty-candidate state that nothing
    # downstream handles.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation("I cannot produce a contract.")
    mock_wrapper.validate.return_value = [make_issue()]

    result = pipeline.run("contract text", _make_config(max_iterations=0))

    candidate = result.candidates[0]
    assert candidate.final_code == "I cannot produce a contract."
    assert candidate.converged is False
    assert candidate.error_history[0].rejected_response is None


# --- Failed external calls (provider / validator) ------------------------------


def test_provider_error_mid_loop_records_a_failed_candidate_with_prior_iterations(mock_deps):
    # The whole point: an exception on correction 1 used to destroy the run
    # directory, the report, and the generation pass that had already succeeded.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.side_effect = [make_generation(_CODE), LLMCallError("Timeout: boom")]
    mock_wrapper.validate.return_value = [make_issue()]

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    candidate = result.candidates[0]
    assert candidate.failure is not None and "boom" in candidate.failure
    assert candidate.final_code == _CODE
    assert len(candidate.error_history) == 1
    assert candidate.iterations_used == 0
    assert candidate.converged is False


def test_provider_error_on_generation_records_an_empty_failed_candidate(mock_deps):
    # Both traps at once. `converged=not blocking` is True here because nothing
    # ever populated `blocking`, which would report a candidate that produced no
    # code as converged; and `len(error_history) - 1` is -1 with no history, a
    # value no Field(ge=0) guards.
    _, mock_llm, _ = mock_deps
    mock_llm.generate.side_effect = LLMCallError("Timeout: boom")

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    candidate = result.candidates[0]
    assert candidate.converged is False
    assert candidate.iterations_used == 0
    assert candidate.final_code == ""
    assert candidate.error_history == []
    assert candidate.failure is not None


def test_failed_candidate_does_not_make_the_run_successful(mock_deps):
    _, mock_llm, _ = mock_deps
    mock_llm.generate.side_effect = LLMCallError("Timeout: boom")

    result = pipeline.run("contract text", _make_config(num_candidates=1, max_iterations=3))

    assert result.success is False
    assert result.failed_candidate_count == 1


def test_a_sibling_converges_when_another_candidate_fails(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.side_effect = [LLMCallError("Timeout: boom"), make_generation(_CODE)]
    mock_wrapper.validate.return_value = []

    result = pipeline.run("contract text", _make_config(num_candidates=2, max_iterations=3))

    assert result.success is True
    assert result.candidates[0].failure is not None
    assert result.candidates[1].failure is None
    assert result.candidates[1].converged is True
    assert result.failed_candidate_count == 1


def test_failed_candidate_keeps_the_tokens_it_spent(mock_deps):
    # The calls that succeeded were billed; dropping them would understate cost
    # in exactly the runs that waste the most of it.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.side_effect = [
        make_generation(_CODE, usage=make_usage(prompt_tokens=100, completion_tokens=50)),
        LLMCallError("Timeout: boom"),
    ]
    mock_wrapper.validate.return_value = [make_issue()]

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    assert result.candidates[0].total_tokens == 150


def test_a_non_provider_exception_still_aborts_the_run(mock_deps):
    # The fence on the catch's narrowness. Widening it to `except Exception`
    # would write this bug into report.json as an external failure — quiet
    # corruption in place of a loud crash.
    _, mock_llm, _ = mock_deps
    mock_llm.generate.side_effect = AttributeError("bug in our own code")

    with pytest.raises(AttributeError):
        pipeline.run("contract text", _make_config(max_iterations=3))


def test_exhausted_candidate_has_no_failure(mock_deps):
    # Negative control: running out of iterations is not a failed call, and the
    # two must stay distinguishable or the artifact cannot tell them apart.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation(_CODE)
    mock_wrapper.validate.return_value = [make_issue()]

    result = pipeline.run("contract text", _make_config(max_iterations=2))

    candidate = result.candidates[0]
    assert candidate.converged is False
    assert candidate.failure is None
    assert result.failed_candidate_count == 0


def test_validator_failure_mid_loop_records_a_failed_candidate(mock_deps):
    # The JAR is the other external call in the loop; a transient validate
    # failure must degrade the same way a provider one does.
    mock_wrapper, mock_llm, _ = mock_deps
    # The two stages return DIFFERENT contracts, or the desync assertion below
    # could not fail: with one shared code, iteration 0's record already agrees
    # with final_code.
    corrected = _CODE.replace("Contract C", "Contract C2")
    usage = make_usage(prompt_tokens=100, completion_tokens=10)
    mock_llm.generate.side_effect = [
        make_generation(_CODE, usage=usage),
        make_generation(corrected, usage=usage),
    ]
    mock_wrapper.validate.side_effect = [
        [make_issue()],
        ValidationCallError("SymboleoAC CLI timed out after 60 seconds"),
    ]

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    candidate = result.candidates[0]
    assert candidate.failure is not None and "timed out" in candidate.failure
    assert candidate.converged is False
    # The correction call was billed and its adopted code is what `final_code`
    # holds, so its record must exist: without the `finally` around validate,
    # the history ends at iteration 0 and disagrees with final_code.
    assert len(candidate.error_history) == 2
    assert candidate.final_code == corrected
    assert candidate.error_history[-1].code == candidate.final_code
    assert candidate.total_tokens == 220


def test_validator_failure_on_the_generation_pass_still_records_its_call(mock_deps):
    # The generation call succeeded and was billed before the JAR died. Dropping
    # its record would zero the tokens AND leave `final_code` — a real contract,
    # written to disk — accounted for by no iteration at all.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation(
        _CODE, usage=make_usage(prompt_tokens=100, completion_tokens=10)
    )
    mock_wrapper.validate.side_effect = ValidationCallError("CLI returned non-JSON output")

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    candidate = result.candidates[0]
    assert candidate.converged is False
    assert candidate.iterations_used == 0
    assert candidate.final_code == _CODE
    assert len(candidate.error_history) == 1
    assert candidate.error_history[0].code == _CODE
    assert candidate.error_history[0].errors == []  # never validated
    assert candidate.total_tokens == 110


def test_cancelled_candidate_is_not_recorded_as_failed(mock_deps):
    # Cancellation returns None rather than raising, so it can never enter the
    # except; this pins that a cancelled run yields no candidates at all.
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = make_generation(_CODE)
    mock_wrapper.validate.return_value = []
    token = CancellationToken()
    token.cancel()

    result = pipeline.run("contract text", _make_config(max_iterations=3), cancel=token)

    assert result.candidates == []
    assert result.failed_candidate_count == 0
