from pydantic import BaseModel


class SymboleoIssue(BaseModel):
    severity: str
    code: str | None
    offset: int
    line: int
    column: int
    length: int
    message: str

    @property
    def is_error(self) -> bool:
        """True for issues that block convergence — the single home for the
        ``"ERROR"`` literal.

        A plain property, not a ``computed_field``: ``severity`` already
        serializes, so a derived boolean in report.json would be redundant
        stored state.
        """
        return self.severity == "ERROR"
