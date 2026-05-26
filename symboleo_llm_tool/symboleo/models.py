from pydantic import BaseModel


class SymboleoIssue(BaseModel):
    severity: str
    code: str | None
    offset: int
    line: int
    column: int
    length: int
    message: str
