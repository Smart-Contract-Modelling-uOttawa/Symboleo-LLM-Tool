"""Advisory model/parameter compatibility checks.

These produce best-effort, non-fatal warnings — they never block a run.

This module is the single home for provider/model-specific parameter knowledge:
which models reject a param, what value range a provider accepts. The dividing
line: universal invariants (temperature within the cross-provider 0–2 envelope,
``max_tokens >= 1``) are hard validators on the config models; anything keyed on
*which* provider or model is in play is advisory and lives here. New quirks of
that kind join these checks rather than scattering across layers.

Signals: model capability comes from LiteLLM (``supports_reasoning``) rather
than a hand-maintained model list, so that check improves automatically as
LiteLLM is upgraded. Provider temperature ranges are hand-maintained below
(LiteLLM's model map carries no param ranges) — acceptable because the table is
tiny, the facts are stable, and an unknown provider yields no warning (see
``temperature_range_warnings``).
"""

import litellm

from symboleo_llm_tool.config.models import LLMConfig, PipelineConfig, SuiteConfig


def reasoning_param_warnings(config: LLMConfig) -> list[str]:
    """Warn when a sampling param is set on a reasoning model that will reject it.

    Reasoning models (OpenAI o-series / GPT-5, Anthropic Opus 4.x / Fable 5) do not
    accept ``temperature`` (and the other sampling params); sending one is dropped
    or returns a 400. ``supports_reasoning`` is used as the signal rather than
    ``get_supported_openai_params`` because the latter is wrong for current
    reasoning models in pinned LiteLLM versions (e.g. BerriAI/litellm#26444), while
    the reasoning-category flag is accurate and false-alarm-free in testing.

    An *unrecognized* model is not an error path: LiteLLM returns ``False`` for it,
    so the ``if not is_reasoning`` branch already yields no warning. The ``try``
    guards only the LiteLLM lookup, and only against an *unexpected* failure —
    because this is advisory, a freak LiteLLM error must degrade to "no warning"
    rather than crash the run. Our own logic stays outside the guard so its bugs
    are not masked.

    ``max_tokens`` is intentionally not checked — LiteLLM translates it to
    ``max_completion_tokens`` for reasoning models, so it is safe to send.
    """
    model = config.litellm_model
    try:
        is_reasoning = litellm.supports_reasoning(model=model)
    except Exception:
        return []
    if not is_reasoning:
        return []

    warnings: list[str] = []
    if config.temperature is not None:
        warnings.append(
            f"temperature={config.temperature} is set, but '{config.model}' is a reasoning "
            "model that does not accept sampling parameters — it will be ignored or rejected. "
            "Remove temperature from this stage's config."
        )
    return warnings


# Temperature ranges each provider's API accepts. The LLMConfig validator
# enforces only the cross-provider envelope (0–2), so an in-envelope value can
# still exceed the selected provider's cap. A provider is listed only when its
# API documents a hard cap; an absent provider (e.g. Cohere, whose Chat API
# documents no upper bound) is deliberate, not an oversight.
_TEMPERATURE_RANGES: dict[str, tuple[float, float]] = {
    "openai": (0.0, 2.0),
    "anthropic": (0.0, 1.0),
}


def temperature_range_warnings(config: LLMConfig) -> list[str]:
    """Warn when a set temperature is outside the provider's accepted range.

    An unknown provider yields no warning — the same fail-quiet contract as the
    reasoning check: a missing table row costs a missed advisory, never a false
    alarm or a blocked run.
    """
    if config.temperature is None:
        return []
    bounds = _TEMPERATURE_RANGES.get(config.provider)
    if bounds is None:
        return []
    low, high = bounds
    if low <= config.temperature <= high:
        return []
    return [
        f"temperature={config.temperature} is outside the {low}–{high} range "
        f"'{config.provider}' accepts — the provider will reject the request. "
        "Adjust or remove this stage's temperature."
    ]


def reasoning_models(models_by_provider: dict[str, list[str]]) -> list[str]:
    """The subset of offered model names that are reasoning models.

    Serves ``GET /options`` so the form can blank and disable its temperature
    field for models that reject one — the seed-side counterpart of the
    None-default guard. The form otherwise seeds 0.2 into every request, and
    ``drop_params`` cannot be trusted to strip it: LiteLLM's supported-params
    table wrongly lists ``temperature`` for current reasoning models (the same
    class of table error as BerriAI/litellm#26444), so the seed reaches the
    provider and returns a 400.

    Same signal and same fail-quiet contract as ``reasoning_param_warnings``:
    an unknown model is simply not flagged, which costs an enabled field and a
    contained 400 — never a blocked run.
    """
    flagged: list[str] = []
    for provider, names in models_by_provider.items():
        for name in names:
            try:
                if litellm.supports_reasoning(model=f"{provider}/{name}"):
                    flagged.append(name)
            except Exception:
                continue
    return flagged


def llm_param_warnings(config: LLMConfig) -> list[str]:
    """All per-``LLMConfig`` advisories — the seam future checks join."""
    return [*reasoning_param_warnings(config), *temperature_range_warnings(config)]


def pipeline_param_warnings(config: PipelineConfig) -> list[str]:
    """Stage-labeled param warnings across all pipeline stages.

    The single place that enumerates stages and applies the ``<stage>: <msg>``
    label, so the CLI and API surface identical, consistent warnings.
    """
    stages = (("generation", config.generation), ("correction", config.correction))
    return [
        f"{label}: {warning}"
        for label, stage in stages
        for warning in llm_param_warnings(stage.llm)
    ]


def suite_param_warnings(suite: SuiteConfig) -> list[tuple[str, str]]:
    """``(experiment name, warning)`` pairs across a suite.

    The single source for the per-experiment param warnings both the CLI and the
    API surface — each formats the pair its own way (Rich markup vs. a plain
    ``<name>: <warning>`` string), but the pairing lives in one place.
    """
    return [
        (experiment.name, warning)
        for experiment in suite.experiments
        for warning in pipeline_param_warnings(experiment.config)
    ]
