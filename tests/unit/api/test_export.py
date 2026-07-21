"""POST /suites/export — build a suite file the CLI can actually run.

The load-bearing assertion is a round trip through ``load_suite_config``, not a
golden string: the export exists so ``symboleo-tool suite`` can re-run a
comparison built in the browser, so "our own loader accepts it and preserves
the settings" is the property that matters. A checked-in expected-output file
would pin formatting the CLI does not care about and go stale on any schema
change.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from symboleo_llm_tool.config.loader import load_suite_config


def _experiment(name: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": name,
        "generation": {"model": "gpt-4o-mini", "strategy": "zero_shot"},
    }
    body.update(overrides)
    return body


def _export(client: TestClient, **body: object) -> dict[str, Any]:
    response = client.post("/api/suites/export", json=body)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def test_returns_a_filename_and_content(client: TestClient) -> None:
    payload = _export(client, experiments=[_experiment("zero-shot")])

    assert payload["filename"] == "suite.yaml"
    assert payload["content"].strip()


def test_content_round_trips_through_the_cli_loader(client: TestClient, tmp_path: Path) -> None:
    # Two experiments on *different providers* with distinct settings, so a
    # model→provider mix-up or a field copied from the wrong experiment fails.
    payload = _export(
        client,
        max_concurrency=4,
        experiments=[
            _experiment(
                "zero-shot",
                generation={"model": "gpt-4o-mini", "strategy": "zero_shot", "temperature": 0.2},
                num_candidates=3,
            ),
            _experiment(
                "cot-haiku",
                generation={"model": "claude-haiku-4-5", "strategy": "cot"},
                max_iterations=7,
            ),
        ],
    )

    path = tmp_path / "suite.yaml"
    path.write_text(payload["content"], encoding="utf-8")
    suite = load_suite_config(path, "Seller shall deliver the goods.")

    assert suite.max_concurrency == 4
    assert [e.name for e in suite.experiments] == ["zero-shot", "cot-haiku"]

    first = suite.experiments[0].config
    assert first.generation.llm.provider == "openai"
    assert first.generation.llm.model == "gpt-4o-mini"
    assert first.generation.llm.temperature == 0.2
    assert first.generation.strategy == "zero_shot"
    assert first.pipeline.num_candidates == 3

    second = suite.experiments[1].config
    assert second.generation.llm.provider == "anthropic"
    assert second.generation.llm.model == "claude-haiku-4-5"
    assert second.generation.strategy == "cot"
    assert second.pipeline.max_iterations == 7


def test_content_omits_machine_specific_and_run_local_settings(client: TestClient) -> None:
    # The file is meant to be portable and hand-editable: a jar path or output
    # directory from the server's filesystem would not survive the trip, and the
    # contract is a CLI argument the loader rejects inside the file.
    payload = _export(client, experiments=[_experiment("zero-shot")])
    data = yaml.safe_load(payload["content"])

    assert "contract_text" not in data
    server_local = {"symboleo", "output", "observability"}
    assert all(server_local.isdisjoint(e["config"]) for e in data["experiments"])


def test_content_omits_values_equal_to_their_default(client: TestClient) -> None:
    # Pins exclude_defaults, and with it the policy split against
    # write_suite_results' full dump — DRYing the two into one call would emit
    # this key and silently pass every other test here.
    payload = _export(
        client,
        experiments=[_experiment("zero-shot", max_iterations=3)],  # 3 == RunConfig default
    )
    data = yaml.safe_load(payload["content"])

    assert "pipeline" not in data["experiments"][0]["config"]


def test_reports_reasoning_model_warnings(client: TestClient) -> None:
    # The exported file can legitimately carry a temperature the model rejects;
    # POST /suites reports that, and an export must not be quieter than a run.
    payload = _export(
        client,
        experiments=[
            _experiment(
                "haiku",
                generation={
                    "model": "claude-haiku-4-5",
                    "strategy": "zero_shot",
                    "temperature": 0.7,
                },
            )
        ],
    )

    assert any("temperature" in w for w in payload["warnings"])
    assert payload["warnings"][0].startswith("haiku: ")


def test_reports_no_warnings_for_a_plain_model(client: TestClient) -> None:
    payload = _export(client, experiments=[_experiment("zero-shot")])

    assert payload["warnings"] == []


def test_few_shot_example_files_survive_as_names(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ties the export to the by-name corpus contract: a path here would only
    # resolve on the machine that exported it.
    #
    # The corpus must be wired up, not merely written to disk: export builds the
    # config through the same validated path a run does, so a few_shot stage
    # resolves its examples. That is not a limitation in practice — the UI
    # populates the example picker from GET /options, i.e. this same corpus.
    corpus = tmp_path / "examples"
    corpus.mkdir()
    (corpus / "sale.yaml").write_text(
        "contract_text: 'Buyer pays.'\nsymboleo_code: 'Contract C(){}'\n", encoding="utf-8"
    )
    monkeypatch.setenv("SYMBOLEO_EXAMPLES_DIR", str(corpus))

    payload = _export(
        client,
        experiments=[
            _experiment(
                "few-shot",
                generation={
                    "model": "gpt-4o-mini",
                    "strategy": "few_shot",
                    "strategy_params": {"example_files": ["sale"]},
                },
            )
        ],
    )

    path = tmp_path / "suite.yaml"
    path.write_text(payload["content"], encoding="utf-8")
    suite = load_suite_config(path, "contract")

    assert suite.experiments[0].config.generation.strategy_params == {"example_files": ["sale"]}


def test_correction_defaults_to_generation_like_a_run(client: TestClient, tmp_path: Path) -> None:
    # The exported file is explicit where the request is not: omitting correction
    # means "same as generation", and the CLI schema has no such shorthand.
    payload = _export(
        client,
        experiments=[
            _experiment(
                "explicit-correction",
                generation={"model": "gpt-4o-mini", "strategy": "zero_shot"},
                correction={"model": "claude-haiku-4-5", "strategy": "cot"},
            ),
            _experiment("implicit-correction"),
        ],
    )

    path = tmp_path / "suite.yaml"
    path.write_text(payload["content"], encoding="utf-8")
    suite = load_suite_config(path, "contract")

    explicit = suite.experiments[0].config.correction
    assert explicit.llm.provider == "anthropic"
    assert explicit.strategy == "cot"

    implicit = suite.experiments[1].config
    assert implicit.correction.llm.model == implicit.generation.llm.model
    assert implicit.correction.strategy == implicit.generation.strategy


def test_unknown_model_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/suites/export",
        json={
            "experiments": [
                _experiment("bad", generation={"model": "gpt-9-ultra", "strategy": "zero_shot"})
            ]
        },
    )

    assert response.status_code == 422
    assert "gpt-9-ultra" in response.json()["detail"]


def test_unknown_strategy_returns_422(client: TestClient) -> None:
    # An export whose strategy the CLI would reject is worse than no export: the
    # failure surfaces later, on another machine, against a file that looks
    # authoritative. Export is built through the same validated path as a run.
    response = client.post(
        "/api/suites/export",
        json={
            "experiments": [
                _experiment("bad", generation={"model": "gpt-4o-mini", "strategy": "zeroshot"})
            ]
        },
    )

    assert response.status_code == 422
    assert "zeroshot" in response.json()["detail"]


def test_unknown_strategy_param_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/suites/export",
        json={
            "experiments": [
                _experiment(
                    "bad",
                    generation={
                        "model": "gpt-4o-mini",
                        "strategy": "zero_shot",
                        "strategy_params": {"exmaple_files": ["sale"]},
                    },
                )
            ]
        },
    )

    assert response.status_code == 422
    assert "exmaple_files" in response.json()["detail"]


def test_duplicate_experiment_names_return_422(client: TestClient) -> None:
    response = client.post(
        "/api/suites/export",
        json={"experiments": [_experiment("same"), _experiment("same")]},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("experiments", [[], None])
def test_missing_experiments_returns_422(client: TestClient, experiments: object) -> None:
    body = {} if experiments is None else {"experiments": experiments}
    response = client.post("/api/suites/export", json=body)

    assert response.status_code == 422
