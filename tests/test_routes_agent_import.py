from fastapi import APIRouter

def test_agent_router_importable():
    from app.routes.agent import router
    assert isinstance(router, APIRouter)

def test_agent_router_has_chat_route():
    from app.routes.agent import router
    paths = {r.path for r in router.routes}
    assert "/api/agent/chat" in paths
