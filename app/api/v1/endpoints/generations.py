from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

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
