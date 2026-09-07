from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.core.exceptions import NotFoundError

from app.api.deps import get_api_key, get_app_services
from app.schemas.common import ApiResponse
from app.schemas.generation import CreateChildTaskRequest, CreateGenerationRequest
from app.services.bootstrap import AppServices


router = APIRouter()


@router.post("", response_model=ApiResponse)
async def create_generation(
    request: CreateGenerationRequest,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    summary = services.generation_service.create(api_key, request)
    return ApiResponse(data=summary)


@router.get("", response_model=ApiResponse)
async def list_generations(
    offset: int = 0,
    limit: int = 20,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    return ApiResponse(data=services.generation_service.list(api_key, offset, limit))


@router.get("/{generation_id}", response_model=ApiResponse)
async def get_generation(
    generation_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    return ApiResponse(data=services.generation_service.get_summary(api_key, generation_id))


@router.post("/{generation_id}/tasks", response_model=ApiResponse)
async def append_child_task(
    generation_id: str,
    request: CreateChildTaskRequest,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    summary = services.generation_service.append_child_task(api_key, generation_id, request.task_type)
    return ApiResponse(data=summary)


@router.get("/{generation_id}/diagrams", response_model=ApiResponse)
async def list_generation_diagrams(
    generation_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    return ApiResponse(data=services.generation_service.list_diagrams(api_key, generation_id))


@router.get("/{generation_id}/body/download")
async def download_generation_body_pptx(
    generation_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
):
    """下载未插入图形的纯文本 body.pptx。

    即使同时选择了 body + diagrams 并做了组装，原始正文 PPTX 仍然可单独下载。
    """
    local_path = services.generation_service.download_body_pptx(api_key, generation_id)
    return FileResponse(
        path=local_path,
        filename=local_path.name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@router.get("/{generation_id}/diagrams/download")
async def download_generation_diagrams_zip(
    generation_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
):
    """下载该 Generation 全部图形 SVG，统一打包为一个 zip。"""
    summary = services.generation_service.get_summary(api_key, generation_id)
    diagram_task_id = summary.get("diagram_task_id")
    if not diagram_task_id:
        raise NotFoundError("该 Generation 没有图形任务")
    zip_path = services.diagram_service.download_all_zip(api_key, diagram_task_id)
    return FileResponse(
        path=zip_path,
        filename=zip_path.name,
        media_type="application/zip",
    )
