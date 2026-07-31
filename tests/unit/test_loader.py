from pathlib import Path

import pytest

from symboleo_llm_tool.config.loader import load_config, load_suite_config

# Every shipped config is load-checked below. `ui_config.yaml` is the only
# exclusion: it is the frontend's model/parameter list, not a pipeline config.
_UI_CONFIG = "ui_config.yaml"
_SUITE_CONFIG = "suite_example.yaml"
_SHIPPED_PIPELINE_CONFIGS = sorted(
    p for p in Path("configs").glob("*.yaml") if p.name not in {_UI_CONFIG, _SUITE_CONFIG}
)


@pytest.mark.parametrize("path", _SHIPPED_PIPELINE_CONFIGS, ids=lambda p: p.name)
def test_shipped_config_loads(path: Path) -> None:
    # Config models are `extra="forbid"`, so a typo in a shipped config is a
    # hard load failure — and without this it surfaces when a user runs the
    # file rather than in CI.
    load_config(path)


def test_shipped_suite_config_loads() -> None:
    # Same guarantee for the one shipped SuiteConfig, which `load_config`
    # cannot parse. The other suite tests below use an inline fixture, so
    # nothing else reads this file.
    load_suite_config(Path("configs") / _SUITE_CONFIG, "Seller shall deliver the goods.")


_SUITE_YAML = """
max_concurrency: 4
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
    # 4, not the SuiteConfig default of 2 — otherwise dropping the key entirely
    # would still satisfy this.
    assert suite.max_concurrency == 4


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
