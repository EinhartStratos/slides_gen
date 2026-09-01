from __future__ import annotations

from typing import Optional

from pydantic import Field, field_validator

from app.core.constants import (
    GENERATION_MODE_LEGACY_HYBRID,
    GENERATION_MODE_SEPARATED_BODY_DIAGRAM,
)
from app.schemas.common import SchemaModel
from app.schemas.task import GenerationOptionsSchema


class GenerationTarget(str):
    """v4 子任务目标枚举兼容类型。"""


class CreateGenerationRequest(SchemaModel):
    """创建 Generation（一次不可变输入）。"""

    generation_mode: str = Field(
        default=GENERATION_MODE_SEPARATED_BODY_DIAGRAM,
        description="生成模式：legacy_hybrid / separated_body_diagram",
    )
    template_id: Optional[str] = Field(default=None, description="模板ID；为空时使用系统默认模板")
    targets: list[str] = Field(
        ...,
        min_length=1,
        description="需要创建的任务类型数组：body / diagrams",
    )
    auto_compose: bool = Field(default=True, description="正文和图形均可用时是否自动组装")
    requirement_text: str = Field(
        ...,
        min_length=1,
        max_length=100000,
        description="上游合并后的全部文档纯文本，1~100000 字符",
    )
    custom_requirements: Optional[str] = Field(default=None, description="本次生成指令，业务优先级最高")
    options: Optional[GenerationOptionsSchema] = Field(default=None, description="模型和执行参数")

    @field_validator("generation_mode")
    @classmethod
    def _validate_generation_mode(cls, v: str) -> str:
        allowed = {GENERATION_MODE_LEGACY_HYBRID, GENERATION_MODE_SEPARATED_BODY_DIAGRAM}
        if v not in allowed:
            raise ValueError(f"generation_mode 必须是 {allowed} 之一")
        return v

    @field_validator("targets")
    @classmethod
    def _validate_targets(cls, v: list[str]) -> list[str]:
        allowed = {"body", "diagrams"}
        if not v:
            raise ValueError("targets 至少包含一项")
        for t in v:
            if t not in allowed:
                raise ValueError(f"targets 中只能包含 {allowed}，收到 {t}")
        if len(set(v)) != len(v):
            raise ValueError("targets 不能重复")
        return v


class ChildTaskSummary(SchemaModel):
    """子任务摘要。"""

    task_id: Optional[str] = Field(default=None, description="任务ID")
    task_type: Optional[str] = Field(default=None, description="任务类型：body/diagrams/compose")
    status: Optional[str] = Field(default=None, description="任务状态")
    current_stage: Optional[str] = Field(default=None, description="当前阶段")
    progress: float = Field(default=0.0, description="进度 0~100")
    ftp_result_pptx_path: Optional[str] = Field(default=None, description="产物 FTP 路径")
    error_message: Optional[str] = Field(default=None, description="错误信息")


class DiagramListItem(SchemaModel):
    """Generation 下的图形摘要。"""

    diagram_id: str = Field(..., description="图形ID")
    task_id: str = Field(..., description="所属任务ID")
    status: str = Field(..., description="图形状态")
    diagram_title: Optional[str] = Field(default=None, description="图形标题")
    section_title: Optional[str] = Field(default=None, description="所属章节标题")
    diagram_kind: Optional[str] = Field(default=None, description="图形类型")
    diagram_description: Optional[str] = Field(default=None, description="图形说明")
    preview_url: Optional[str] = Field(default=None, description="SVG 预览 URL（相对路径）")
    download_url: Optional[str] = Field(default=None, description="SVG 下载 URL（相对路径）")
    final_page_no: Optional[int] = Field(default=None, description="组装后最终页码；SVG-only 为空")


class GenerationSummary(SchemaModel):
    """Generation 聚合状态。"""

    generation_id: str = Field(..., description="输入ID")
    generation_mode: str = Field(..., description="生成模式")
    status: str = Field(..., description="聚合状态")
    auto_compose: bool = Field(..., description="是否自动组装")
    requirement_text_chars: int = Field(..., description="需求文本字符数")
    requirement_text_warning: bool = Field(default=False, description="是否超过5万字告警")
    template_id: Optional[str] = Field(default=None, description="模板ID")
    body_task_id: Optional[str] = Field(default=None, description="正文任务ID")
    diagram_task_id: Optional[str] = Field(default=None, description="图形任务ID")
    compose_task_id: Optional[str] = Field(default=None, description="组装任务ID")
    body_status: str = Field(..., description="正文状态")
    diagram_status: str = Field(..., description="图形状态")
    compose_status: str = Field(..., description="组装状态")
    kept_page_count: Optional[int] = Field(default=None, description="保留页数")
    skipped_page_count: Optional[int] = Field(default=None, description="跳过页数")
    diagram_count: Optional[int] = Field(default=None, description="图形数量")
    body_pptx_artifact_id: Optional[str] = Field(default=None, description="正文 PPTX 产物ID")
    composed_pptx_artifact_id: Optional[str] = Field(default=None, description="组装 PPTX 产物ID")
    has_body_download: bool = Field(default=False, description="是否可下载正文 PPTX")
    has_diagram_downloads: bool = Field(default=False, description="是否有可下载图形")
    has_composed_download: bool = Field(default=False, description="是否可下载组装 PPTX")
    warning_message: Optional[str] = Field(default=None, description="告警信息")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    completed_at: Optional[str] = Field(default=None, description="完成时间")


class GenerationListItem(SchemaModel):
    """Generation 列表项。"""

    generation_id: str = Field(..., description="输入ID")
    generation_mode: str = Field(..., description="生成模式")
    status: str = Field(..., description="聚合状态")
    requirement_text_chars: int = Field(..., description="需求文本字符数")
    body_status: str = Field(..., description="正文状态")
    diagram_status: str = Field(..., description="图形状态")
    compose_status: str = Field(..., description="组装状态")
    template_id: Optional[str] = Field(default=None, description="模板ID")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    completed_at: Optional[str] = Field(default=None, description="完成时间")


class CreateChildTaskRequest(SchemaModel):
    """后续补触发 body/diagrams 子任务。"""

    task_type: str = Field(..., description="任务类型：body / diagrams")

    @field_validator("task_type")
    @classmethod
    def _validate_task_type(cls, v: str) -> str:
        allowed = {"body", "diagrams"}
        if v not in allowed:
            raise ValueError(f"task_type 必须是 {allowed} 之一")
        return v
