"""Tests for the tool registry."""
import asyncio

import pytest


def test_register_adds_tool():
    from app.agent.tools import _REGISTRY, _register, get_openai_tools, is_write_tool

    @_register({
        "type": "function",
        "function": {
            "name": "_test_tool",
            "description": "test",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        "write": False,
    })
    async def _fn(**_): return "ok"

    assert "_test_tool" in _REGISTRY
    specs = {t["function"]["name"]: t for t in get_openai_tools()}
    assert specs["_test_tool"]["function"]["name"] == "_test_tool"
    assert not is_write_tool("_test_tool")


def test_register_marks_write_tools():
    from app.agent.tools import _register, is_write_tool

    @_register({
        "type": "function",
        "function": {"name": "_write_t", "description": "w",
                     "parameters": {"type": "object", "properties": {}, "required": []}},
        "write": True,
    })
    async def _wfn(**_): return "written"

    assert is_write_tool("_write_t")


def test_dispatch_calls_handler():
    from app.agent.tools import _register, dispatch

    @_register({
        "type": "function",
        "function": {"name": "_dispatch_t", "description": "d",
                     "parameters": {"type": "object", "properties": {}, "required": []}},
        "write": False,
    })
    async def _dfn(**_): return {"dispatched": True}

    result = asyncio.get_event_loop().run_until_complete(dispatch("_dispatch_t", "{}"))
    assert result == {"dispatched": True}


def test_dispatch_unknown_raises_keyerror():
    from app.agent.tools import dispatch
    with pytest.raises(KeyError, match="Unknown tool: nonexistent"):
        asyncio.get_event_loop().run_until_complete(dispatch("nonexistent", "{}"))
