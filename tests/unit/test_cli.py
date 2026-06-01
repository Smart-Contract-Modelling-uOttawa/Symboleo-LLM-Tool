from symboleo_llm_tool.cli.main import _format_progress
from symboleo_llm_tool.symboleo.models import SymboleoIssue


def _make_error() -> SymboleoIssue:
    return SymboleoIssue(
        severity="ERROR", code=None, offset=0, line=1, column=1, length=1, message="err"
    )


def test_generation_with_errors():
    msg = _format_progress(0, 0, [_make_error()], num_candidates=1, max_iterations=3)
    assert "Generated" in msg
    assert "1 error(s)" in msg


def test_generation_converged():
    msg = _format_progress(0, 0, [], num_candidates=1, max_iterations=3)
    assert "Generated" in msg
    assert "converged" in msg


def test_correction_with_errors_remaining():
    msg = _format_progress(0, 2, [_make_error(), _make_error()], num_candidates=1, max_iterations=3)
    assert "Correction 2/3" in msg
    assert "2 error(s) remaining" in msg


def test_correction_converged():
    msg = _format_progress(0, 1, [], num_candidates=1, max_iterations=3)
    assert "Correction 1/3" in msg
    assert "converged" in msg


def test_multi_candidate_shows_prefix():
    msg = _format_progress(1, 0, [], num_candidates=3, max_iterations=3)
    assert "Candidate 2/3" in msg


def test_single_candidate_no_prefix():
    msg = _format_progress(0, 0, [], num_candidates=1, max_iterations=3)
    assert "Candidate" not in msg
