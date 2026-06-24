from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

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


def _suite(*strategies: str) -> SuiteConfig:
    return SuiteConfig(
        contract_text="contract text",
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

    def fake_run(contract_text, config, input_file="", on_progress=None):
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
