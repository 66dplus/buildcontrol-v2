from fastapi import APIRouter

def test_projects_router_importable():
    from app.routes.projects import router
    assert isinstance(router, APIRouter)

def test_projects_router_has_cache_state():
    from app.routes import projects as pm
    assert hasattr(pm, "_PROJECT_LISTS_CACHE")
    assert hasattr(pm, "_LIST_META_CACHE")
    assert hasattr(pm, "_get_list_context")

def test_projects_router_has_12_routes():
    from app.routes.projects import router
    paths = {r.path for r in router.routes}
    required = {
        "/api/projects",
        "/api/projects/{project_id}/materials",
        "/api/projects/{project_id}/labor",
        "/api/projects/{project_id}/task-context",
        "/api/projects/{project_id}/tasks",
        "/api/projects/{project_id}/stages",
        "/api/projects/{project_id}/subtasks",
        "/api/projects/{project_id}/equipment",
        "/api/projects/{project_id}/tasks-full",
        "/api/projects/{project_id}/materials-all",
        "/api/projects/{project_id}/labor-all",
        "/api/projects/{project_id}/equipment-all",
    }
    assert required.issubset(paths)
