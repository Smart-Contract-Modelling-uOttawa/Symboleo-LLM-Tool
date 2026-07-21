"""The few-shot example corpus, addressed by name.

``example_files`` in ``strategy_params`` holds example *names*, never paths, so
a config means the same thing on every machine and survives a round trip
through a suite file. Resolution to a real file happens here, at point of use.

Deliberately not in the config loader: resolving there would leave the
in-memory model holding machine-specific paths, so everything that dumps a
config -- the run record, the suite file, the export -- would emit them again.
"""

import os
from pathlib import Path, PureWindowsPath

import yaml

_DEFAULT_DIR = Path("examples")
_ENV_VAR = "SYMBOLEO_EXAMPLES_DIR"


def _examples_dir() -> Path:
    """Directory holding the corpus, CWD-relative unless overridden.

    Read per call rather than captured at import: import-time capture would pin
    the value for a long-running API process, and would land before the CLI's
    ``load_dotenv()``, so a ``.env`` entry could never take effect.
    """
    # An empty value falls back rather than resolving to Path("") == CWD, which
    # is what an unset key in a Docker env_file produces.
    override = os.environ.get(_ENV_VAR)
    return Path(override) if override else _DEFAULT_DIR


def list_example_names() -> list[str]:
    directory = _examples_dir()
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.yaml"))


def load_example(name: str) -> dict[str, str]:
    """Load the ``contract_text``/``symboleo_code`` pair named ``name``."""
    _reject_path_form(name)
    directory = _examples_dir()
    path = directory / f"{name}.yaml"
    if not path.exists():
        available = ", ".join(list_example_names()) or "none"
        raise ValueError(f"Example {name!r} not found in {directory} (available: {available})")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "contract_text" not in data or "symboleo_code" not in data:
        raise ValueError(f"Example {name!r} must have 'contract_text' and 'symboleo_code' keys")
    return {"contract_text": data["contract_text"], "symboleo_code": data["symboleo_code"]}


def _reject_path_form(name: str) -> None:
    """Reject entries the corpus cannot address.

    A separator would mean a subdirectory, which ``list_example_names`` does not
    enumerate; a ``.yaml`` suffix would resolve to ``<name>.yaml.yaml``.

    Rejecting separators is also what confines resolution to the corpus:
    ``example_files`` arrives unfiltered from an HTTP request body, and
    ``<corpus>/../secret.yaml`` would otherwise read a file from outside it into
    the prompt. Supporting subdirectories later needs a containment check, not
    merely a wider enumeration.
    """
    if "/" in name or "\\" in name or name.endswith(".yaml"):
        # PureWindowsPath, not Path: it treats both separators as separators on
        # every platform, so a config written on Windows still gets a usable
        # suggestion when it runs in the Linux container.
        raise ValueError(
            f"example_files takes example names, not paths: "
            f"use {PureWindowsPath(name).stem!r}, not {name!r}"
        )
