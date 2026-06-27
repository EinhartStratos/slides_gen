from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import Field

from app.schemas.common import SchemaModel


class PageGenerationResult(SchemaModel):
    page_no: int = Field(..., description="页码")
    page_name: str = Field(..., description="页面名称")
    should_generate: bool = Field(default=True, description="该页是否生成")
    skip_reason: str = Field(default="", description="跳过原因")
    decision_source: str = Field(default="heuristic", description="判定来源")
    generated_svg: str | None = Field(default=None, description="LLM 生成的完整 SVG 文本")
    raw_response_text: str | None = Field(default=None, description="模型原始返回文本")


class BasePageGenerationClient(ABC):
    @abstractmethod
    def generate_page_svg(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        page_name: str,
        svg_content: str,
    ) -> PageGenerationResult:
        raise NotImplementedError
