from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import Field

from app.schemas.common import SchemaModel


class PagePlanResult(SchemaModel):
    page_no: int = Field(..., description="页码")
    page_name: str = Field(..., description="页面名称")
    should_generate: bool = Field(default=True, description="该页是否生成")
    skip_reason: str = Field(default="", description="跳过原因")
    page_type: str = Field(default="content", description="页面类型：cover/toc/content/diagram/end")
    page_title: str = Field(default="", description="该页标题")
    decision_source: str = Field(default="heuristic", description="判定来源")
    raw_response_text: str | None = Field(default=None, description="模型原始返回文本")


class PageGenerationResult(SchemaModel):
    page_no: int = Field(..., description="页码")
    page_name: str = Field(..., description="页面名称")
    generated_svg: str | None = Field(default=None, description="LLM 生成的完整 SVG 文本")
    decision_source: str = Field(default="heuristic", description="判定来源")
    raw_response_text: str | None = Field(default=None, description="模型原始返回文本")


class BasePageGenerationClient(ABC):
    @abstractmethod
    def plan_single_page(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        page_name: str,
        svg_content: str,
        total_pages: int = 0,
        model: str | None = None,
        enable_thinking: bool = False,
    ) -> PagePlanResult:
        raise NotImplementedError

    @abstractmethod
    def generate_page_svg(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        page_name: str,
        page_type: str,
        page_title: str,
        svg_content: str,
        model: str | None = None,
        enable_thinking: bool = False,
    ) -> PageGenerationResult:
        raise NotImplementedError
