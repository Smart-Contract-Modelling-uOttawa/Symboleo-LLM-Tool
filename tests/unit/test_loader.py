from pathlib import Path

import pytest

from symboleo_llm_tool.config.loader import load_suite_config

_SUITE_YAML = """
max_concurrency: 2
experiments:
  - name: zero-shot
    config:
      generation:
        llm: {provider: openai, model: gpt-4o-mini}
        strategy: zero_shot
      correction:
        llm: {provider: openai, model: gpt-4o-mini}
        strategy: zero_shot
  - name: cot
    config:
      generation:
        llm: {provider: openai, model: gpt-4o-mini}
        strategy: cot
      correction:
        llm: {provider: openai, model: gpt-4o-mini}
        strategy: zero_shot
"""


def test_load_suite_config_binds_cli_contract(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text(_SUITE_YAML, encoding="utf-8")

    suite = load_suite_config(path, "Seller shall deliver the goods.")

    assert suite.contract_text == "Seller shall deliver the goods."
    assert [e.name for e in suite.experiments] == ["zero-shot", "cot"]
    assert suite.max_concurrency == 2


def test_load_suite_config_rejects_inline_contract(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text("contract_text: pasted contract\n" + _SUITE_YAML, encoding="utf-8")

    with pytest.raises(ValueError, match="must not contain 'contract_text'"):
        load_suite_config(path, "the CLI-supplied contract")


def test_load_suite_config_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "suite.yaml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a YAML mapping"):
        load_suite_config(path, "contract")
