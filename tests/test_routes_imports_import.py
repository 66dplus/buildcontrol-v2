from fastapi import APIRouter

def test_imports_router_importable():
    from app.routes.imports import router, _import_jobs
    assert isinstance(router, APIRouter)
    assert isinstance(_import_jobs, dict)

def test_imports_router_has_routes():
    from app.routes.imports import router
    paths = {r.path for r in router.routes}
    assert "/upload" in paths
    assert "/api/import-status/{job_id}" in paths
