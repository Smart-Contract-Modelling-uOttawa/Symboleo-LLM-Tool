from pydantic import BaseModel


class SymboleoIssue(BaseModel):
    severity: str
    code: str | None
    offset: int
    line: int
    column: int
    length: int
    message: str
    # Structured extras the validator attaches out of band. Mirrors the CLI's
    # `data` array verbatim rather than flattening to a single hint string: the
    # array is the wire format, and a second element would otherwise be lost
    # silently. Absent for every issue the JAR does not annotate, and for every
    # issue at all on a JAR predating hint support — hence the default.
    data: list[str] | None = None

    @property
    def hint(self) -> str | None:
        """Advisory guidance the validator attached beside this issue.

        A property rather than a stored field for the same reason as
        ``is_error``: ``data`` already serializes, so persisting the derived
        value would be redundant state in ``report.json``. Advisory by contract
        — the wording is upstream's to change, so never assert on it.
        """
        return self.data[0] if self.data else None

    @property
    def is_error(self) -> bool:
        """True for issues that block convergence — the single home for the
        ``"ERROR"`` literal.

        A plain property, not a ``computed_field``: ``severity`` already
        serializes, so a derived boolean in report.json would be redundant
        stored state.
        """
        return self.severity == "ERROR"
