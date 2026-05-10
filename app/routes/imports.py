import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from bitrix.client import BitrixClient
from config import settings
from scripts.import_excel import ExcelImporter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["imports"])

# In-memory store for async import jobs: job_id → {status, filename, result?, error?}
_import_jobs: Dict[str, Dict[str, Any]] = {}


async def _run_import_job(job_id: str, tmp_path: str, filename: str, custom_name: Optional[str]) -> None:
    """Background task: run Excel import and store result in _import_jobs."""
    try:
        async with BitrixClient() as client:
            importer = ExcelImporter(client)
            result = await importer.import_file(tmp_path, custom_name=custom_name)
        logger.info(f"[job={job_id}] Import complete: project_id={result['summary']['project_id']}")
        _import_jobs[job_id]["status"] = "done"
        _import_jobs[job_id]["result"] = result["summary"]
    except Exception as e:
        logger.error(f"[job={job_id}] Import failed for {filename}: {e}")
        _import_jobs[job_id]["status"] = "error"
        _import_jobs[job_id]["error"] = str(e)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/upload")
async def upload_excel(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    project_name: str = Form(default=""),
) -> JSONResponse:
    """
    Upload an Excel file (.xlsx) and kick off a background import.

    Returns immediately with a job_id. Poll GET /api/import-status/{job_id}
    to track progress. Status values: "running" | "done" | "error".
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail=f"File must be .xlsx or .xls, got: {file.filename}",
        )

    try:
        settings.validate()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Server config error: {e}")

    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix, prefix=Path(file.filename).stem + "_"
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from openpyxl import load_workbook
        wb = load_workbook(tmp_path, read_only=True, data_only=True)
        wb.close()
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        logger.warning(f"Rejected upload {file.filename}: failed to parse Excel ({e})")
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось открыть Excel-файл: {e}",
        )

    job_id = uuid.uuid4().hex[:10]
    _import_jobs[job_id] = {"status": "running", "filename": file.filename}
    logger.info(f"[job={job_id}] Received {file.filename} ({len(content)} bytes) → {tmp_path}")

    custom_name = (project_name or "").strip() or None
    background_tasks.add_task(_run_import_job, job_id, tmp_path, file.filename, custom_name)

    return JSONResponse(status_code=202, content={"job_id": job_id, "status": "running"})


@router.get("/api/import-status/{job_id}")
async def import_status(job_id: str) -> JSONResponse:
    """Poll import job status. Returns status + result/error when done."""
    job = _import_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return JSONResponse(content=job)
