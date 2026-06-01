from pydantic import BaseModel, Field

from symboleo_llm_tool.output.models import IterationRecord
from symboleo_llm_tool.symboleo.models import SymboleoIssue


class PromptContext(BaseModel):
    contract_text: str | None = None
    current_code: str | None = None
    errors: list[SymboleoIssue] = Field(default_factory=list)
    grammar_context: str | None = None
    history: list[IterationRecord] | None = None
