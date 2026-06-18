import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from symboleo_llm_tool.symboleo.models import SymboleoIssue

_SUBPROCESS_TIMEOUT_SECONDS = 60


class SymboleoWrapper:
    def __init__(self, jar_path: Path, java_executable: str = "java") -> None:
        self._jar = jar_path
        self._java = java_executable
        self._preflight()

    def _preflight(self) -> None:
        if not shutil.which(self._java):
            raise RuntimeError(
                f"Java executable '{self._java}' not found on PATH. "
                "Install Java 17+ from https://adoptium.net/ "
                "and ensure it is on your PATH."
            )
        if not self._jar.exists():
            raise RuntimeError(
                f"SymboleoAC JAR not found at: {self._jar}. "
                "Ensure the JAR is present at the configured path."
            )

    def validate(self, code: str) -> list[SymboleoIssue]:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".symboleo", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = Path(f.name)

        try:
            result = subprocess.run(
                [self._java, "-jar", str(self._jar), str(tmp_path), "-f", "json", "-q"],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"SymboleoAC CLI timed out after {_SUBPROCESS_TIMEOUT_SECONDS} seconds"
            ) from e
        finally:
            tmp_path.unlink(missing_ok=True)

        if result.returncode == 2:
            raise RuntimeError(f"SymboleoAC CLI error: {result.stderr.strip()}")

        stdout = result.stdout.strip()
        if result.returncode == 1 and not stdout:
            raise RuntimeError(
                f"SymboleoAC CLI exited with errors but produced no output. "
                f"stderr: {result.stderr.strip()}"
            )
        if not stdout:
            return []

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"SymboleoAC CLI returned non-JSON output: {stdout!r}") from e
        return [SymboleoIssue(**issue) for issue in data.get("issues", [])]
