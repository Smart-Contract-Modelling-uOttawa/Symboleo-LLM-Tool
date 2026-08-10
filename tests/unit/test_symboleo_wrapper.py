import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper, ValidationCallError


@pytest.fixture
def wrapper(tmp_path: Path) -> SymboleoWrapper:
    jar = tmp_path / "test.jar"
    jar.touch()
    with patch("shutil.which", return_value="/usr/bin/java"):
        return SymboleoWrapper(jar_path=jar, java_executable="java")


def _mock_result(returncode: int, stdout: dict) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = json.dumps(stdout)
    m.stderr = ""
    return m


def _raw_result(returncode: int, stdout: str, stderr: str = "") -> MagicMock:
    """A result whose stdout is not necessarily JSON — for the failure paths."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _issue(severity: str, line: int, message: str, code: Any = None) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "offset": 10,
        "line": line,
        "column": 5,
        "length": 3,
        "message": message,
    }


def test_validate_returns_empty_list_when_no_errors(wrapper: SymboleoWrapper) -> None:
    payload = {"summary": {"total": 0, "warnings": 0, "errors": 0}, "issues": []}
    with patch("subprocess.run", return_value=_mock_result(0, payload)):
        issues = wrapper.validate("valid symboleo code")
    assert issues == []


def test_validate_returns_issues_when_errors_present(wrapper: SymboleoWrapper) -> None:
    payload = {
        "summary": {"total": 1, "warnings": 0, "errors": 1},
        "issues": [
            {
                "severity": "ERROR",
                "code": None,
                "offset": 10,
                "line": 2,
                "column": 5,
                "length": 3,
                "message": "missing ';'",
            }
        ],
    }
    with patch("subprocess.run", return_value=_mock_result(1, payload)):
        issues = wrapper.validate("invalid code")
    assert len(issues) == 1
    assert issues[0].line == 2
    assert issues[0].column == 5
    assert issues[0].message == "missing ';'"


def test_validate_carries_the_hint_a_jar_attaches_out_of_band(wrapper: SymboleoWrapper) -> None:
    """The `data` array survives parsing and surfaces through `.hint`.

    Guidance travels beside the message rather than inside it, so nothing here
    can be recovered by string-matching `message` — if this parsing regresses,
    hints silently stop reaching the correction prompt while every other
    assertion in the suite stays green.
    """
    hint = "'Number' is a base type and cannot be the type of a declared variable"
    payload = {
        "summary": {"total": 2, "warnings": 0, "errors": 2},
        "issues": [
            {
                "severity": "ERROR",
                "code": "ca.uottawa.csmlab.symboleo.syntaxHint",
                "offset": 10,
                "line": 2,
                "column": 5,
                "length": 3,
                "message": "mismatched input 'Number' expecting RULE_ID",
                "data": [hint],
            },
            {
                "severity": "ERROR",
                "code": None,
                "offset": 20,
                "line": 3,
                "column": 1,
                "length": 1,
                "message": "extraneous input ')'",
                "data": None,
            },
        ],
    }
    with patch("subprocess.run", return_value=_mock_result(1, payload)):
        issues = wrapper.validate("invalid code")
    assert issues[0].hint == hint
    assert issues[0].message == "mismatched input 'Number' expecting RULE_ID"
    assert issues[1].hint is None


def test_validate_tolerates_a_jar_that_emits_no_data_field(wrapper: SymboleoWrapper) -> None:
    # Every JAR before hint support omits `data` entirely. The field must
    # default rather than raise, or adopting the plumbing ahead of the jar
    # would break every run against the shipped one.
    payload = {
        "summary": {"total": 1, "warnings": 0, "errors": 1},
        "issues": [
            {
                "severity": "ERROR",
                "code": None,
                "offset": 0,
                "line": 1,
                "column": 1,
                "length": 1,
                "message": "no viable alternative at input 'Assign'",
            }
        ],
    }
    with patch("subprocess.run", return_value=_mock_result(1, payload)):
        issues = wrapper.validate("invalid code")
    assert issues[0].data is None
    assert issues[0].hint is None


def test_validate_parses_every_issue_preserving_order_and_severity(
    wrapper: SymboleoWrapper,
) -> None:
    # Real validator output is multi-issue with mixed severities; a single-issue
    # fixture cannot tell list parsing from "parse the first one". Severity is
    # load-bearing — the integration test and the convergence rule both key on it.
    payload = {
        "summary": {"total": 3, "warnings": 1, "errors": 1},
        "issues": [
            _issue("ERROR", 87, "'endContrct' is not declared", code="org.eclipse.xtext.Syntax"),
            _issue("WARNING", 41, "Declared instance 'storage' is never used"),
            _issue("INFO", 78, "granting authority note"),
        ],
    }
    with patch("subprocess.run", return_value=_mock_result(1, payload)):
        issues = wrapper.validate("invalid code")

    assert [i.severity for i in issues] == ["ERROR", "WARNING", "INFO"]
    assert [i.line for i in issues] == [87, 41, 78]
    assert issues[0].code == "org.eclipse.xtext.Syntax"
    # is_error is the convergence gate's predicate. INFO must group with
    # WARNING, not with ERROR — the non-blocking side is everything non-ERROR.
    assert [i.is_error for i in issues] == [True, False, False]


def test_validate_raises_when_the_cli_times_out(wrapper: SymboleoWrapper) -> None:
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="java", timeout=60)):
        with pytest.raises(ValidationCallError, match="timed out after 60 seconds"):
            wrapper.validate("anything")


def test_validate_raises_when_errors_reported_without_output(wrapper: SymboleoWrapper) -> None:
    # Exit code 1 promises an issue report; an empty stdout means the JAR broke
    # rather than "no issues", so it must not be read as a clean run.
    with patch("subprocess.run", return_value=_raw_result(1, "", stderr="boom")):
        with pytest.raises(ValidationCallError, match="produced no output"):
            wrapper.validate("anything")


def test_validate_raises_on_non_json_output(wrapper: SymboleoWrapper) -> None:
    with patch("subprocess.run", return_value=_raw_result(0, "Exception in thread main")):
        with pytest.raises(ValidationCallError, match="non-JSON output"):
            wrapper.validate("anything")


def test_validate_raises_when_an_issue_is_missing_fields(wrapper: SymboleoWrapper) -> None:
    # A JAR whose report schema drifted must fail loudly — these tests exist
    # because swapping the JAR is a routine, documented operation.
    payload = {"summary": {}, "issues": [{"severity": "ERROR", "message": "no position fields"}]}
    with patch("subprocess.run", return_value=_mock_result(1, payload)):
        with pytest.raises(ValidationCallError, match="unexpected issue format"):
            wrapper.validate("anything")


def test_validate_returns_empty_when_a_clean_run_prints_nothing(wrapper: SymboleoWrapper) -> None:
    with patch("subprocess.run", return_value=_raw_result(0, "")):
        assert wrapper.validate("valid code") == []


def test_validate_raises_on_cli_failure(wrapper: SymboleoWrapper) -> None:
    m = MagicMock()
    m.returncode = 2
    m.stdout = ""
    m.stderr = "usage error"
    with patch("subprocess.run", return_value=m):
        with pytest.raises(ValidationCallError, match="SymboleoAC CLI error"):
            wrapper.validate("anything")


def test_preflight_raises_when_java_missing(tmp_path: Path) -> None:
    jar = tmp_path / "test.jar"
    jar.touch()
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="Java executable"):
            SymboleoWrapper(jar_path=jar)


def test_preflight_raises_when_jar_missing(tmp_path: Path) -> None:
    with patch("shutil.which", return_value="/usr/bin/java"):
        with pytest.raises(RuntimeError, match="JAR not found"):
            SymboleoWrapper(jar_path=tmp_path / "missing.jar")


def test_validate_raises_when_the_cli_cannot_be_spawned(wrapper: SymboleoWrapper) -> None:
    # Preflight passed at construction, so a later OSError is transient and
    # external — a full temp dir, a file lock, memory pressure under a
    # concurrent suite — and must degrade the candidate, not the run.
    with patch("subprocess.run", side_effect=OSError("cannot allocate memory")):
        with pytest.raises(ValidationCallError, match="Could not invoke"):
            wrapper.validate("code")


def test_preflight_failure_stays_a_plain_runtime_error(tmp_path: Path) -> None:
    # Pins the split's classification: ValidationCallError means *transient*,
    # and a missing JAR is not. Preflight runs at construction in
    # pipeline.run(), outside the candidate boundary, so it aborts regardless
    # of type today — the plain RuntimeError is what keeps that abort if
    # wrapper construction ever moves inside the boundary.
    with patch("shutil.which", return_value="/usr/bin/java"):
        with pytest.raises(RuntimeError) as exc_info:
            SymboleoWrapper(jar_path=tmp_path / "missing.jar")
    assert not isinstance(exc_info.value, ValidationCallError)
