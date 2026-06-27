from __future__ import annotations

from fastapi import Header, HTTPException, Request

from app.core.config import get_settings
from app.services.bootstrap import AppServices


def get_api_key(x_llm_api_key: str | None = Header(default=None, alias="X-LLM-API-Key")) -> str:
    if not x_llm_api_key:
        raise HTTPException(status_code=401, detail="缺少请求头 X-LLM-API-Key")
    return x_llm_api_key


def get_optional_api_key(x_llm_api_key: str | None = Header(default=None, alias="X-LLM-API-Key")) -> str | None:
    return x_llm_api_key


def get_app_services(request: Request) -> AppServices:
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise HTTPException(status_code=500, detail="服务尚未完成初始化")
    return services


def get_settings_dep():
    return get_settings()
