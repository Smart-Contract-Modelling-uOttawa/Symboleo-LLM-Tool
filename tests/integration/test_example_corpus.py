"""Every shipped few-shot example must still pass the validator.

The corpus is prompt content, not reference data: an example teaches whatever it
demonstrates, so one that stopped validating would feed invalid SymboleoAC to
every ``few_shot`` run and the loop would spend its whole budget correcting a
mistake the prompt supplied. Nothing else covers this -- the `tests/fixtures/`
contracts are separate files, and no unit test reads the corpus.

Only possible now that `examples/` is tracked; while it was gitignored this file
would have collected zero cases in CI.

ERROR-severity only, matching the convergence rule: warnings are allowed here for
the same reason they are allowed on `valid.symboleo` (see the fixture policy in
CLAUDE.md, "Testing Strategy").
"""

from pathlib import Path

import pytest

from symboleo_llm_tool.prompts.examples import list_example_names, load_example
from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper

JAR_PATH = Path("./lib/symboleo-cli.jar")


@pytest.fixture(scope="module")
def wrapper() -> SymboleoWrapper:
    return SymboleoWrapper(jar_path=JAR_PATH)


def test_corpus_is_not_empty() -> None:
    """Guards the parametrize below, which would collect zero cases on an empty
    corpus -- the file would pass while testing nothing."""
    assert list_example_names(), "no examples found; expected the corpus in examples/"


@pytest.mark.parametrize("name", list_example_names())
def test_shipped_example_validates(wrapper: SymboleoWrapper, name: str) -> None:
    errors = [i for i in wrapper.validate(load_example(name)["symboleo_code"]) if i.is_error]
    detail = "; ".join(f"line {e.line}: {e.message}" for e in errors)
    assert errors == [], f"{name} no longer validates -- {detail}"
