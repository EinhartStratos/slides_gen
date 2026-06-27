from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.deps import get_api_key, get_app_services
from app.schemas.common import ApiResponse
from app.schemas.task import CreateGenerationTaskRequest
from app.services.bootstrap import AppServices


router = APIRouter()


@router.get("/tasks", response_model=ApiResponse)
async def list_tasks(
    status: str | None = None,
    offset: int = 0,
    limit: int = 20,
    ids_only: bool = False,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    data = services.task_service.list_tasks(api_key, status, offset, limit, ids_only)
    return ApiResponse(data=data)


@router.post("/tasks", response_model=ApiResponse)
async def create_task(
    request: CreateGenerationTaskRequest,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    summary = services.task_service.create_task(api_key, request)
    task_id = summary["task_id"]
    services.container.task_runner.submit(
        task_id,
        lambda: services.orchestration_service.run_task(api_key, task_id),
    )
    return ApiResponse(data=summary)


@router.get("/tasks/{task_id}", response_model=ApiResponse)
async def get_task(
    task_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    return ApiResponse(data=services.task_service.get_task_summary(api_key, task_id))


@router.get("/tasks/{task_id}/pages", response_model=ApiResponse)
async def get_task_pages(
    task_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    return ApiResponse(data=services.task_service.list_pages(api_key, task_id))


@router.get("/tasks/{task_id}/events", response_model=ApiResponse)
async def get_task_events(
    task_id: str,
    limit: int = 100,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    return ApiResponse(data=services.task_service.list_events(api_key, task_id, limit))


@router.get("/tasks/{task_id}/artifacts", response_model=ApiResponse)
async def get_task_artifacts(
    task_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    return ApiResponse(data=services.task_service.list_artifacts(api_key, task_id))


@router.get("/tasks/{task_id}/download")
async def download_task_result(
    task_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
):
    task = services.task_service.get_task(api_key, task_id)
    ftp_path = task.get("ftp_result_pptx_path")
    if not ftp_path or task.get("status") != "completed":
        return ApiResponse(code=409, message="任务尚未完成，暂不可下载", data=None)
    task_workspace = services.container.workspace.task(task_id)
    local_path = services.container.ftp.download_file(str(ftp_path), task_workspace.result_pptx_path)
    download_name = Path(str(ftp_path)).name or local_path.name
    return FileResponse(
        path=local_path,
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@router.post("/tasks/{task_id}/stop", response_model=ApiResponse)
async def stop_task(
    task_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    return ApiResponse(data=services.task_service.request_stop(api_key, task_id))


@router.post("/tasks/{task_id}/resume", response_model=ApiResponse)
async def resume_task(
    task_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    payload = services.task_service.mark_resume_requested(api_key, task_id)
    services.container.task_runner.submit(
        task_id,
        lambda: services.orchestration_service.run_task(api_key, task_id),
    )
    return ApiResponse(data=payload)
