from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from symboleo_llm_tool.config.models import (
    LLMConfig,
    PipelineConfig,
    RunConfig,
    StageConfig,
)
from symboleo_llm_tool.pipeline import pipeline
from tests.helpers import make_issue


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
        patch(
            "symboleo_llm_tool.pipeline.pipeline.SymboleoWrapper"
        ) as mock_wrapper_cls,
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
    mock_llm.generate.return_value = "valid symboleo"
    mock_wrapper.validate.return_value = []

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    assert result.success is True
    assert result.candidates[0].converged is True
    assert result.candidates[0].iterations_used == 0
    assert mock_llm.generate.call_count == 1


def test_stops_at_max_iterations_when_always_errors(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = "invalid"
    mock_wrapper.validate.return_value = [make_issue()]

    result = pipeline.run("contract text", _make_config(max_iterations=3))

    assert result.success is False
    assert result.candidates[0].converged is False
    assert result.candidates[0].iterations_used == 3


def test_error_history_length_matches_iterations(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = "invalid"
    mock_wrapper.validate.return_value = [make_issue()]

    result = pipeline.run("contract text", _make_config(max_iterations=2))

    # iteration 0 (generation) + iterations 1 and 2 (correction)
    assert len(result.candidates[0].error_history) == 3


def test_stop_on_first_convergence_halts_remaining_candidates(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = "valid"
    mock_wrapper.validate.return_value = []

    result = pipeline.run(
        "contract text",
        _make_config(num_candidates=3, stop_on_first_convergence=True),
    )

    assert len(result.candidates) == 1
    assert result.success is True


def test_all_candidates_run_when_stop_on_first_convergence_false(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = "valid"
    mock_wrapper.validate.return_value = []

    result = pipeline.run(
        "contract text",
        _make_config(num_candidates=3, stop_on_first_convergence=False),
    )

    assert len(result.candidates) == 3


def test_on_progress_called_after_generation(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = "valid"
    mock_wrapper.validate.return_value = []

    progress = MagicMock()
    pipeline.run("contract text", _make_config(max_iterations=3), on_progress=progress)

    progress.assert_called_once_with(0, 0, [])


def test_on_progress_called_after_each_correction(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = "invalid"
    error = make_issue()
    mock_wrapper.validate.side_effect = [[error], [error], []]

    progress = MagicMock()
    pipeline.run("contract text", _make_config(max_iterations=3), on_progress=progress)

    assert progress.call_args_list == [
        call(0, 0, [error]),
        call(0, 1, [error]),
        call(0, 2, []),
    ]


def test_grammar_load_failure_propagates(mock_deps):
    with patch(
        "symboleo_llm_tool.pipeline.pipeline._load_grammar",
        side_effect=RuntimeError("Failed to load Symboleo grammar resource"),
    ):
        with pytest.raises(RuntimeError, match="Failed to load Symboleo grammar resource"):
            pipeline.run("contract text", _make_config())


def test_clean_response_strips_markdown_fences(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = "```symboleo\nContract Test() {}\n```"
    mock_wrapper.validate.return_value = []

    result = pipeline.run("contract text", _make_config())

    assert result.candidates[0].final_code == "Contract Test() {}"


def test_clean_response_strips_plain_fences(mock_deps):
    mock_wrapper, mock_llm, _ = mock_deps
    mock_llm.generate.return_value = "```\nContract Test() {}\n```"
    mock_wrapper.validate.return_value = []

    result = pipeline.run("contract text", _make_config())

    assert result.candidates[0].final_code == "Contract Test() {}"
