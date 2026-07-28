from pathlib import Path

import pytest

from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper

JAR_PATH = Path("./lib/symboleo-cli.jar")
FIXTURES = Path("tests/fixtures")


@pytest.fixture(scope="module")
def wrapper() -> SymboleoWrapper:
    return SymboleoWrapper(jar_path=JAR_PATH)


@pytest.fixture(scope="module")
def invalid_issues(wrapper: SymboleoWrapper) -> list:
    code = (FIXTURES / "invalid.symboleo").read_text(encoding="utf-8")
    return wrapper.validate(code)


def test_valid_contract_returns_no_errors(wrapper: SymboleoWrapper) -> None:
    code = (FIXTURES / "valid.symboleo").read_text(encoding="utf-8")
    issues = wrapper.validate(code)
    # A valid AC contract yields no ERROR-severity issues. The validator may
    # still emit stylistic WARNINGs (e.g. unused declarations), which do not
    # make the contract invalid.
    errors = [issue for issue in issues if issue.is_error]
    assert errors == []


def test_invalid_contract_returns_errors(invalid_issues: list) -> None:
    assert len(invalid_issues) > 0


def test_invalid_contract_error_has_expected_fields(invalid_issues: list) -> None:
    issue = invalid_issues[0]
    assert issue.severity in ("ERROR", "WARNING")
    assert isinstance(issue.line, int)
    assert isinstance(issue.column, int)
    assert isinstance(issue.message, str) and len(issue.message) > 0
