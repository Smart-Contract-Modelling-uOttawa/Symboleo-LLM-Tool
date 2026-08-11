from pathlib import Path

import pytest
import yaml

from symboleo_llm_tool.config.loader import load_config, load_suite_config

# Every shipped run config is load-checked below. The glob is deliberately
# non-recursive: configs/*.yaml at the top level are pipeline/suite configs by
# directory contract, while subdirectories hold other kinds — configs/app/ is
# the deployment's (ui_config.yaml, fenced by test_compatibility.py's shipped
# ui-config tests) and configs/schemas/ is generated JSON.


def _shipped_configs() -> tuple[list[Path], list[Path]]:
    """Shipped configs split into (pipeline, suite) by shape, not by filename.

    `experiments` is the key that decides which loader parses a file, so it is
    the honest partition. A name list would need hand-editing for every new
    suite file, and the failure is silent in the worse direction: the file gets
    excluded from the pipeline list and load-checked by nothing.
    """
    pipeline, suite = [], []
    for path in sorted(Path("configs").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        (suite if "experiments" in data else pipeline).append(path)
    return pipeline, suite


_SHIPPED_PIPELINE_CONFIGS, _SHIPPED_SUITE_CONFIGS = _shipped_configs()


def test_both_shipped_kinds_are_present() -> None:
    # An empty parametrize list passes vacuously, so a glob that stopped
    # matching would silently retire every case below.
    assert _SHIPPED_PIPELINE_CONFIGS and _SHIPPED_SUITE_CONFIGS


@pytest.mark.parametrize("path", _SHIPPED_PIPELINE_CONFIGS, ids=lambda p: p.name)
def test_shipped_config_loads(path: Path) -> None:
    # Config models are `extra="forbid"`, so a typo in a shipped config is a
    # hard load failure — and without this it surfaces when a user runs the
    # file rather than in CI.
    load_config(path)


@pytest.mark.parametrize("path", _SHIPPED_SUITE_CONFIGS, ids=lambda p: p.name)
def test_shipped_suite_config_loads(path: Path) -> None:
    # Same guarantee for the shipped SuiteConfigs, which `load_config` cannot
    # parse. The other suite tests below use an inline fixture, so nothing else
    # reads these files.
    load_suite_config(path, "Seller shall deliver the goods.")


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
