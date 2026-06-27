from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import health, templates, tasks


api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(templates.router, prefix="/templates", tags=["templates"])
api_router.include_router(tasks.router, tags=["tasks"])
