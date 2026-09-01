from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import diagrams, generations, health, tasks, templates


api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(templates.router, prefix="/templates", tags=["templates"])
api_router.include_router(tasks.router, tags=["tasks"])
api_router.include_router(generations.router, prefix="/generations", tags=["generations"])
api_router.include_router(diagrams.router, prefix="/tasks", tags=["diagrams"])
