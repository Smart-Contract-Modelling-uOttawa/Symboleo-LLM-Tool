from dataclasses import dataclass, field

from symboleo_llm_tool.output.models import IterationRecord
from symboleo_llm_tool.symboleo.models import SymboleoIssue


@dataclass
class PromptContext:
    contract_text: str | None = None
    current_code: str | None = None
    errors: list[SymboleoIssue] = field(default_factory=list)
    grammar_context: str | None = None
    history: list[IterationRecord] | None = None
