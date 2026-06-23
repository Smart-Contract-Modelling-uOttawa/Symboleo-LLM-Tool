"""Advisory model/parameter compatibility checks.

These produce best-effort, non-fatal warnings — they never block a run. The
model-capability signal comes from LiteLLM (``supports_reasoning``) rather than a
hand-maintained model list, so the checks improve automatically as LiteLLM is
upgraded.
"""

import litellm

from symboleo_llm_tool.config.models import LLMConfig, PipelineConfig


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


def pipeline_param_warnings(config: PipelineConfig) -> list[str]:
    """Stage-labeled param warnings across all pipeline stages.

    The single place that enumerates stages and applies the ``<stage>: <msg>``
    label, so the CLI and API surface identical, consistent warnings.
    """
    stages = (("generation", config.generation), ("correction", config.correction))
    return [
        f"{label}: {warning}"
        for label, stage in stages
        for warning in reasoning_param_warnings(stage.llm)
    ]
