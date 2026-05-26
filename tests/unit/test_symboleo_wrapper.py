import json
from pathlib import Path
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


def test_validate_returns_empty_list_when_no_errors(wrapper: SymboleoWrapper) -> None:
    payload = {"summary": {"total": 0, "warnings": 0, "errors": 0}, "issues": []}
    with patch("subprocess.run", return_value=_mock_result(0, payload)):
        issues = wrapper.validate("valid symboleo code")
    assert issues == []


def test_validate_returns_issues_when_errors_present(wrapper: SymboleoWrapper) -> None:
    payload = {
        "summary": {"total": 1, "warnings": 0, "errors": 1},
        "issues": [
            {"severity": "ERROR", "code": None, "offset": 10, "line": 2, "column": 5, "length": 3, "message": "missing ';'"}
        ],
    }
    with patch("subprocess.run", return_value=_mock_result(1, payload)):
        issues = wrapper.validate("invalid code")
    assert len(issues) == 1
    assert issues[0].line == 2
    assert issues[0].column == 5
    assert issues[0].message == "missing ';'"


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
