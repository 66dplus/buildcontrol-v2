from fastapi import APIRouter


def test_reports_router_importable():
    from app.routes.reports import router
    assert isinstance(router, APIRouter)


def test_reports_router_has_routes():
    from app.routes.reports import router
    paths = {r.path for r in router.routes}
    assert "/api/report" in paths
    assert "/api/purchase-request" in paths
    assert "/api/buyer-report" in paths
