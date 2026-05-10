from fastapi import APIRouter


def test_dashboard_router_importable():
    from app.routes.dashboard import router
    assert isinstance(router, APIRouter)


def test_dashboard_router_has_routes():
    from app.routes.dashboard import router
    paths = {r.path for r in router.routes}
    assert "/api/dashboard/summary" in paths
    assert "/api/whoami" in paths
    assert "/api/projects/{project_id}/phases" in paths
