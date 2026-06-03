from symboleo_llm_tool.symboleo.models import SymboleoIssue


def make_issue(
    *,
    severity: str = "ERROR",
    code: str | None = None,
    offset: int = 0,
    line: int = 1,
    column: int = 1,
    length: int = 1,
    message: str = "syntax error",
) -> SymboleoIssue:
    return SymboleoIssue(
        severity=severity,
        code=code,
        offset=offset,
        line=line,
        column=column,
        length=length,
        message=message,
    )
