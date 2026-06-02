from typing import Any, Callable

from symboleo_llm_tool.prompts.base import PromptStrategy

_registry: dict[str, type[PromptStrategy]] = {}


def register(name: str) -> Callable[[type[PromptStrategy]], type[PromptStrategy]]:
    def decorator(cls: type[PromptStrategy]) -> type[PromptStrategy]:
        _registry[name] = cls
        return cls
    return decorator


def get_strategy(name: str, params: dict[str, Any]) -> PromptStrategy:
    if name not in _registry:
        available = list(_registry.keys())
        raise ValueError(f"Unknown strategy '{name}'. Available: {available}")
    return _registry[name](params)


def list_strategies() -> list[str]:
    return list(_registry.keys())
