"""Tests for the tool registry."""
import asyncio
import importlib


def test_register_adds_tool():
    import app.agent.tools as pkg
    importlib.reload(pkg)
    from app.agent.tools import _register, TOOL_REGISTRY

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

    assert "_test_tool" in TOOL_REGISTRY
    schema, _, is_write = TOOL_REGISTRY["_test_tool"]
    assert schema["function"]["name"] == "_test_tool"
    assert not is_write


def test_register_marks_write_tools():
    from app.agent.tools import _register, TOOL_REGISTRY

    @_register({
        "type": "function",
        "function": {"name": "_write_t", "description": "w",
                     "parameters": {"type": "object", "properties": {}, "required": []}},
        "write": True,
    })
    async def _wfn(**_): return "written"

    _, _, is_write = TOOL_REGISTRY["_write_t"]
    assert is_write


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


def test_dispatch_unknown_returns_error():
    from app.agent.tools import dispatch
    result = asyncio.get_event_loop().run_until_complete(dispatch("nonexistent", "{}"))
    assert "error" in result
