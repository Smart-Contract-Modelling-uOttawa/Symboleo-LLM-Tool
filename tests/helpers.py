from typing import Any

from symboleo_llm_tool.llm.base import GenerationResult
from symboleo_llm_tool.output.models import TokenUsage
from symboleo_llm_tool.symboleo.models import SymboleoIssue


async def passthrough_threadpool(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Stand-in for ``run_in_threadpool`` that calls through synchronously.

    The API bridges await the threadpool twice (the run, then the writer), so a
    single ``AsyncMock`` return value would leak the first hop's result into the
    write hop. Calling through lets each hop's own patch supply its value.
    """
    return func(*args, **kwargs)


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
