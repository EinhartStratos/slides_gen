from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SchemaModel(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class ApiResponse(SchemaModel):
    code: int = Field(default=0, description="业务状态码，0 表示成功")
    message: str = Field(default="ok", description="返回消息")
    data: Any = Field(default=None, description="响应数据")
