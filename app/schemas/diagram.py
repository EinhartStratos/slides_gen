from __future__ import annotations

from typing import Optional

from pydantic import Field

from app.schemas.common import SchemaModel


class DiagramMetadata(SchemaModel):
    """图形完整 metadata。"""

    diagram_id: str = Field(..., description="图形唯一ID")
    generation_id: str = Field(..., description="所属输入ID")
    task_id: str = Field(..., description="所属图形任务ID")
    page_key: Optional[str] = Field(default=None, description="稳定页键")
    template_page_no: Optional[int] = Field(default=None, description="模板页码")
    final_page_no: Optional[int] = Field(default=None, description="组装后最终页码")
    diagram_title: Optional[str] = Field(default=None, description="图形标题")
    section_title: Optional[str] = Field(default=None, description="所属章节标题")
    diagram_kind: Optional[str] = Field(default=None, description="图形类型")
    diagram_description: Optional[str] = Field(default=None, description="图形说明")
    version: int = Field(default=1, description="版本号")
    status: str = Field(..., description="图形状态")
    validation_status: Optional[str] = Field(default=None, description="校验状态")
    ftp_original_svg_path: Optional[str] = Field(default=None, description="原始 SVG FTP 路径")
    ftp_final_svg_path: Optional[str] = Field(default=None, description="最终 SVG FTP 路径")
    preview_url: Optional[str] = Field(default=None, description="预览 URL")
    download_url: Optional[str] = Field(default=None, description="下载 URL")
    evidence_quotes: list[str] = Field(default_factory=list, description="判断依据原文摘录")
    applied_rule_ids: list[str] = Field(default_factory=list, description="命中的全局规则 ID")
    layout_decision: Optional[dict] = Field(default=None, description="布局决策")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    updated_at: Optional[str] = Field(default=None, description="更新时间")
    completed_at: Optional[str] = Field(default=None, description="完成时间")


class DiagramList(SchemaModel):
    """图形列表响应。"""

    generation_id: str = Field(..., description="输入ID")
    task_id: Optional[str] = Field(default=None, description="图形任务ID")
    diagrams: list[dict] = Field(default_factory=list, description="图形摘要列表")
