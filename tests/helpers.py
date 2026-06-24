from symboleo_llm_tool.llm.base import GenerationResult
from symboleo_llm_tool.output.models import TokenUsage
from symboleo_llm_tool.symboleo.models import SymboleoIssue


def make_usage(
    *,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    cost_usd: float | None = 0.001,
) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
    )


def make_generation(
    text: str = "valid symboleo", *, usage: TokenUsage | None = None
) -> GenerationResult:
    return GenerationResult(generated_text=text, usage=usage if usage is not None else make_usage())


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
