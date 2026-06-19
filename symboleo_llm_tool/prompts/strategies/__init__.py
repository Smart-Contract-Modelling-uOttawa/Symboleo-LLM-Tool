from typing import Any

from symboleo_llm_tool.prompts.base import PromptStrategy
from symboleo_llm_tool.prompts.strategies.cot import CoTStrategy
from symboleo_llm_tool.prompts.strategies.few_shot import FewShotStrategy
from symboleo_llm_tool.prompts.strategies.zero_shot import ZeroShotStrategy

_STRATEGIES: dict[str, type[PromptStrategy]] = {
    "zero_shot": ZeroShotStrategy,
    "few_shot": FewShotStrategy,
    "cot": CoTStrategy,
}


def get_strategy(name: str, params: dict[str, Any]) -> PromptStrategy:
    if name not in _STRATEGIES:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(_STRATEGIES.keys())}")
    return _STRATEGIES[name](params)


def list_strategies() -> list[str]:
    return list(_STRATEGIES.keys())
