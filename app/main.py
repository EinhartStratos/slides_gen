from __future__ import annotations

import traceback
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import setup_logging
from app.schemas.common import ApiResponse
from app.services.bootstrap import build_services


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging()
    services = build_services(settings)
    print(settings.llm_base_url)
    print(settings.llm_model)
    services.builtin_template_service.repository.db.ping()
    services.container.workspace.ensure_runtime_dirs()
    try:
        services.builtin_template_service.ensure_default_template()
    except Exception as exc:
        logger.warning("默认模板预热失败: %s", traceback.format_exc())
    app.state.settings = settings
    app.state.services = services
    yield


app = FastAPI(title="slides_gen_server", lifespan=lifespan)
app.include_router(api_router, prefix=get_settings().api_prefix)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiResponse(code=exc.status_code, message=exc.message, data=None).model_dump(mode="json"),
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=ApiResponse(code=500, message=str(exc), data=None).model_dump(mode="json"),
    )
