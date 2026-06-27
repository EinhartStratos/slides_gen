from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import get_api_key, get_app_services, get_optional_api_key
from app.schemas.common import ApiResponse
from app.services.bootstrap import AppServices


router = APIRouter()


@router.get("", response_model=ApiResponse)
async def list_templates(
    api_key: str | None = Depends(get_optional_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    items = [
        services.template_service.serialize_summary(item)
        for item in services.template_service.list_templates(api_key)
    ]
    return ApiResponse(data=items)


@router.get("/{template_id}", response_model=ApiResponse)
async def get_template(
    template_id: str,
    api_key: str | None = Depends(get_optional_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    template = services.template_service.get_accessible_template(api_key, template_id)
    return ApiResponse(data=services.template_service.serialize_detail(template))


@router.post("/import", response_model=ApiResponse)
async def import_template(
    template_name: str = Form(...),
    template_file: UploadFile = File(...),
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    payload = await services.template_import_service.import_template(api_key, template_name, template_file)
    return ApiResponse(data=services.template_service.serialize_import_result(payload))


@router.post("/import-builtin", response_model=ApiResponse)
async def import_builtin_template(
    template_name: str | None = Form(default=None),
    template_file: UploadFile | None = File(default=None),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    payload = await services.builtin_template_service.import_builtin_template(template_name, template_file)
    return ApiResponse(data=services.template_service.serialize_import_result(payload))
