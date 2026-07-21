import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from symboleo_llm_tool.symboleo.wrapper import SymboleoWrapper


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


def test_validate_raises_when_the_cli_times_out(wrapper: SymboleoWrapper) -> None:
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="java", timeout=60)):
        with pytest.raises(RuntimeError, match="timed out after 60 seconds"):
            wrapper.validate("anything")


def test_validate_raises_when_errors_reported_without_output(wrapper: SymboleoWrapper) -> None:
    # Exit code 1 promises an issue report; an empty stdout means the JAR broke
    # rather than "no issues", so it must not be read as a clean run.
    with patch("subprocess.run", return_value=_raw_result(1, "", stderr="boom")):
        with pytest.raises(RuntimeError, match="produced no output"):
            wrapper.validate("anything")


def test_validate_raises_on_non_json_output(wrapper: SymboleoWrapper) -> None:
    with patch("subprocess.run", return_value=_raw_result(0, "Exception in thread main")):
        with pytest.raises(RuntimeError, match="non-JSON output"):
            wrapper.validate("anything")


def test_validate_raises_when_an_issue_is_missing_fields(wrapper: SymboleoWrapper) -> None:
    # A JAR whose report schema drifted must fail loudly — these tests exist
    # because swapping the JAR is a routine, documented operation.
    payload = {"summary": {}, "issues": [{"severity": "ERROR", "message": "no position fields"}]}
    with patch("subprocess.run", return_value=_mock_result(1, payload)):
        with pytest.raises(RuntimeError, match="unexpected issue format"):
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
        with pytest.raises(RuntimeError, match="SymboleoAC CLI error"):
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
