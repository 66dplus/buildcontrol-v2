"""Agent tool registry.

Tools register via the ``@_register(spec)`` decorator at import time.
``core.py`` discovers them through ``get_openai_tools``/``dispatch``/``is_write_tool``.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List

ToolFn = Callable[..., Awaitable[Any]]

_REGISTRY: Dict[str, Dict[str, Any]] = {}


def _register(spec: Dict[str, Any]) -> Callable[[ToolFn], ToolFn]:
    """Register a tool function with its OpenAI-style spec.

    The spec must contain ``function.name``. ``spec["write"]`` (bool) marks
    mutating tools so the orchestrator can gate them behind approval.
    """
    name = spec["function"]["name"]

    def decorator(fn: ToolFn) -> ToolFn:
        _REGISTRY[name] = {"spec": spec, "fn": fn, "write": bool(spec.get("write"))}
        return fn

    return decorator


def get_openai_tools() -> List[Dict[str, Any]]:
    """Return tool specs in the shape OpenAI's chat.completions expects."""
    return [
        {"type": entry["spec"]["type"], "function": entry["spec"]["function"]}
        for entry in _REGISTRY.values()
    ]


def is_write_tool(name: str) -> bool:
    entry = _REGISTRY.get(name)
    return bool(entry and entry["write"])


async def dispatch(name: str, args_json: str) -> Any:
    """Invoke a registered tool by name with JSON-encoded args."""
    entry = _REGISTRY.get(name)
    if not entry:
        raise KeyError(f"Unknown tool: {name}")
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON args for tool {name}: {e}") from e
    if not isinstance(args, dict):
        raise ValueError(f"Tool {name} expects a JSON object, got {type(args).__name__}")
    return await entry["fn"](**args)
