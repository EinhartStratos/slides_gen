from __future__ import annotations

from typing import Optional

from pydantic import Field

from app.schemas.common import SchemaModel


class GenerationOptionsSchema(SchemaModel):
    max_page_concurrency: Optional[int] = Field(default=None, description="单任务分页最大并发数")
    keep_artifacts: Optional[bool] = Field(default=None, description="是否保留中间产物到 FTP")
    output_filename: Optional[str] = Field(default=None, description="最终输出文件名建议")


class CreateGenerationTaskRequest(SchemaModel):
    task_id: Optional[str] = Field(default=None, description="任务ID；为空时由服务端生成")
    requirement_text: str = Field(..., description="本次 PPT 生成需求全文")
    template_id: Optional[str] = Field(default=None, description="模板ID；为空时使用系统默认模板")
    options: Optional[GenerationOptionsSchema] = Field(default=None, description="任务执行参数")


class GenerationTaskSummarySchema(SchemaModel):
    task_id: str = Field(..., description="系统内部任务唯一ID")
    status: str = Field(..., description="任务状态")
    current_stage: str = Field(..., description="任务当前所处阶段")
    progress: float = Field(..., description="任务进度，范围 0 到 100")
    template_id: Optional[str] = Field(default=None, description="本次任务使用的模板ID")
    ftp_result_pptx_path: Optional[str] = Field(default=None, description="最终 PPTX 在 FTP 上的路径")
    error_message: Optional[str] = Field(default=None, description="任务失败时的错误信息")
    created_at: Optional[str] = Field(default=None, description="任务创建时间")
    completed_at: Optional[str] = Field(default=None, description="任务完成时间")


class GenerationTaskPageSchema(SchemaModel):
    task_id: str = Field(..., description="所属任务ID")
    page_no: int = Field(..., description="页码，从 1 开始")
    page_name: Optional[str] = Field(default=None, description="页面名称")
    should_generate: Optional[bool] = Field(default=None, description="该页是否应保留到最终 PPT")
    skip_reason: Optional[str] = Field(default=None, description="页面被跳过时的原因")
    status: str = Field(..., description="分页执行状态")
    diagram_kind: Optional[str] = Field(default=None, description="图形类型，例如 architecture 或 sequence")
    ftp_generated_svg_path: Optional[str] = Field(default=None, description="原始生成 SVG 在 FTP 上的路径")
    ftp_final_svg_path: Optional[str] = Field(default=None, description="最终确认用于转 PPTX 的 SVG 在 FTP 上的路径")
    error_message: Optional[str] = Field(default=None, description="该页执行失败时的错误信息")


class TaskArtifactSchema(SchemaModel):
    artifact_id: str = Field(..., description="产物唯一ID")
    task_id: str = Field(..., description="所属任务ID")
    page_no: Optional[int] = Field(default=None, description="关联页码，为空表示任务级产物")
    artifact_type: str = Field(..., description="产物类型")
    ftp_path: str = Field(..., description="产物在 FTP 上的路径")
    file_name: Optional[str] = Field(default=None, description="文件名")
    is_final: bool = Field(..., description="是否最终产物")
    status: str = Field(..., description="产物状态")
    created_at: Optional[str] = Field(default=None, description="创建时间")


class TaskEventSchema(SchemaModel):
    event_id: str = Field(..., description="事件唯一ID")
    task_id: str = Field(..., description="所属任务ID")
    page_no: Optional[int] = Field(default=None, description="关联页码")
    event_type: str = Field(..., description="事件类型")
    event_stage: Optional[str] = Field(default=None, description="事件发生时所处阶段")
    event_message: Optional[str] = Field(default=None, description="事件说明")
    event_detail: Optional[dict] = Field(default=None, description="事件详情")
    created_at: Optional[str] = Field(default=None, description="创建时间")


class TaskStopResumeResponseSchema(SchemaModel):
    task_id: str = Field(..., description="任务ID")
    status: str = Field(..., description="任务状态")
    stop_requested: bool = Field(..., description="是否已请求停止")
    resume_count: int = Field(default=0, description="任务恢复次数")
