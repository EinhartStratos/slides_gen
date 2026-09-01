from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, Response

from app.api.deps import get_api_key, get_app_services
from app.schemas.common import ApiResponse
from app.services.bootstrap import AppServices


router = APIRouter()


@router.get("/{task_id}/diagrams/{diagram_id}", response_model=ApiResponse)
async def get_diagram(
    task_id: str,
    diagram_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> ApiResponse:
    return ApiResponse(data=services.diagram_service.get_metadata(api_key, task_id, diagram_id))


@router.get("/{task_id}/diagrams/{diagram_id}/preview")
async def preview_diagram(
    task_id: str,
    diagram_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> Response:
    svg_text = services.diagram_service.preview_svg(api_key, task_id, diagram_id)
    return Response(
        content=svg_text,
        media_type="image/svg+xml",
        headers={
            "Content-Security-Policy": "default-src 'none'; script-src 'none';",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{task_id}/diagrams/{diagram_id}/download")
async def download_diagram(
    task_id: str,
    diagram_id: str,
    api_key: str = Depends(get_api_key),
    services: AppServices = Depends(get_app_services),
) -> FileResponse:
    local_path = services.diagram_service.download_svg(api_key, task_id, diagram_id)
    return FileResponse(
        path=local_path,
        filename=Path(str(local_path)).name,
        media_type="image/svg+xml",
    )
