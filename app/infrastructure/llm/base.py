from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import Field

from app.schemas.common import SchemaModel


class PageAnalysisResult(SchemaModel):
    page_no: int = Field(..., description="页码")
    page_name: str = Field(..., description="页面名称")
    should_generate: bool = Field(default=True, description="该页是否生成")
    skip_reason: str = Field(default="", description="跳过原因")
    page_title: str = Field(default="", description="页面标题")
    page_summary: str = Field(default="", description="页面摘要")
    bullet_points: list[str] = Field(default_factory=list, description="要点列表")
    diagram_kind: str | None = Field(default=None, description="图形类型")
    decision_source: str = Field(default="heuristic", description="判定来源")
    raw_response_text: str | None = Field(default=None, description="模型原始返回文本")


class BasePageAnalysisClient(ABC):
    @abstractmethod
    def analyze_page(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        page_name: str,
        svg_excerpt: str,
    ) -> PageAnalysisResult:
        raise NotImplementedError
