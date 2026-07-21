"""The example corpus: names in, content out.

Directory resolution is asserted through the public surface rather than through
``_examples_dir``, so these pin the behaviour ("a corpus here is found") rather
than the constant that currently implements it.
"""

from pathlib import Path

import pytest

from symboleo_llm_tool.prompts.examples import list_example_names, load_example

_EXAMPLE_CONTENT = (
    "contract_text: 'Buyer shall pay $100.'\nsymboleo_code: 'Contract Example(...) ...'\n"
)


def _write_corpus(directory: Path, *names: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / f"{name}.yaml").write_text(_EXAMPLE_CONTENT, encoding="utf-8")
    return directory


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = _write_corpus(tmp_path / "corpus", "sale")
    monkeypatch.setenv("SYMBOLEO_EXAMPLES_DIR", str(directory))
    return directory


def test_defaults_to_a_cwd_relative_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Docker mounts the corpus at /app/examples with WORKDIR /app, so the
    # default must resolve against the CWD rather than the package location.
    _write_corpus(tmp_path / "examples", "sale")
    monkeypatch.delenv("SYMBOLEO_EXAMPLES_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    assert list_example_names() == ["sale"]


def test_empty_env_var_falls_back_to_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Path("") is the CWD, not examples/ -- an unset key in a Docker env_file
    # arrives as an empty string and must not silently repoint the corpus.
    _write_corpus(tmp_path / "examples", "sale")
    monkeypatch.setenv("SYMBOLEO_EXAMPLES_DIR", "")
    monkeypatch.chdir(tmp_path)

    assert list_example_names() == ["sale"]


def test_env_var_overrides_the_directory(corpus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A decoy at the default location: without the override this returns
    # ["decoy"], so the assertion cannot pass by accident.
    _write_corpus(corpus.parent / "examples", "decoy")
    monkeypatch.chdir(corpus.parent)

    assert list_example_names() == ["sale"]


def test_env_var_is_read_per_call(corpus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Import-time capture would pin the value for a long-running API process.
    assert list_example_names() == ["sale"]

    other = _write_corpus(corpus.parent / "other", "lease")
    monkeypatch.setenv("SYMBOLEO_EXAMPLES_DIR", str(other))

    assert list_example_names() == ["lease"]


def test_loads_an_example_by_name(corpus: Path) -> None:
    example = load_example("sale")

    assert example == {
        "contract_text": "Buyer shall pay $100.",
        "symboleo_code": "Contract Example(...) ...",
    }


def test_lists_names_without_the_extension(corpus: Path) -> None:
    _write_corpus(corpus, "lease")
    (corpus / "notes.txt").write_text("ignored", encoding="utf-8")

    assert list_example_names() == ["lease", "sale"]


def test_lists_nothing_when_the_directory_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYMBOLEO_EXAMPLES_DIR", "no/such/dir")

    assert list_example_names() == []


def test_missing_example_names_what_is_available(corpus: Path) -> None:
    with pytest.raises(ValueError, match="not found.*available: sale"):
        load_example("lease")


def test_malformed_example_is_rejected(corpus: Path) -> None:
    (corpus / "bad.yaml").write_text("wrong_key: value\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must have"):
        load_example("bad")


@pytest.mark.parametrize(
    "entry",
    ["examples/sale.yaml", "./examples/sale.yaml", "examples\\sale.yaml", "sale.yaml"],
)
def test_rejects_path_shaped_entries(entry: str, corpus: Path) -> None:
    # A separator means a subdirectory list_example_names does not enumerate,
    # and a .yaml suffix would resolve to sale.yaml.yaml. Neither can address a
    # real example.
    with pytest.raises(ValueError, match="names, not paths"):
        load_example(entry)


@pytest.mark.parametrize("entry", ["./examples/sale.yaml", "examples\\sale.yaml"])
def test_path_shaped_error_suggests_the_bare_name(entry: str, corpus: Path) -> None:
    # Both separators, because the suggestion is computed with a platform-fixed
    # parser: a config authored on Windows is run in the Linux container, and a
    # posix parser there would suggest 'examples\sale' and fail again.
    with pytest.raises(ValueError, match="use 'sale'"):
        load_example(entry)


def test_rejects_a_traversing_entry(corpus: Path) -> None:
    # example_files reaches load_example unfiltered from an HTTP body. Without
    # the separator check this reads a file outside the corpus into the prompt.
    outside = corpus.parent / "secret.yaml"
    outside.write_text(_EXAMPLE_CONTENT, encoding="utf-8")

    with pytest.raises(ValueError, match="names, not paths"):
        load_example("../secret")
