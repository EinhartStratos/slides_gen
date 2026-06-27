from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_app_services
from app.schemas.common import ApiResponse
from app.services.bootstrap import AppServices


router = APIRouter()


@router.get("/health", response_model=ApiResponse)
async def health_check(services: AppServices = Depends(get_app_services)) -> ApiResponse:
    db_ok = services.container.db.ping()
    ftp_ok = services.container.ftp.ping()
    ftp_mode = "remote+mock" if services.container.ftp.remote_enabled else "mock_only"
    return ApiResponse(
        data={
            "status": "ok" if db_ok and ftp_ok else "degraded",
            "database": db_ok,
            "ftp": ftp_ok,
            "ftp_mode": ftp_mode,
            "mock_ftp_dir": str(services.container.ftp.mock_root),
        }
    )
