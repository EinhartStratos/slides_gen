from __future__ import annotations

from typing import Optional

from pydantic import Field

from app.schemas.common import SchemaModel


class TemplateSummarySchema(SchemaModel):
    template_id: str = Field(..., description="模板唯一ID")
    template_name: str = Field(..., description="模板名称")
    source_type: str = Field(..., description="模板来源类型，例如 builtin 或 custom")
    source_filename: Optional[str] = Field(default=None, description="源文件名")
    slide_count: Optional[int] = Field(default=None, description="模板页数")
    status: str = Field(..., description="模板状态")
    is_builtin: bool = Field(..., description="是否内置模板")
    created_at: Optional[str] = Field(default=None, description="模板创建时间")


class TemplateDetailSchema(TemplateSummarySchema):
    source_ftp_path: Optional[str] = Field(default=None, description="模板源 PPTX 在 FTP 上的路径")
    imported_svg_dir_ftp_path: Optional[str] = Field(default=None, description="模板导入后的 layered SVG 目录 FTP 路径")
    imported_svg_flat_dir_ftp_path: Optional[str] = Field(default=None, description="模板导入后的 flat SVG 目录 FTP 路径")
    assets_ftp_dir_path: Optional[str] = Field(default=None, description="模板资源目录 FTP 路径")
    manifest_ftp_path: Optional[str] = Field(default=None, description="模板清单文件 FTP 路径")


class TemplateImportResponseSchema(SchemaModel):
    template_id: str = Field(..., description="新导入模板的唯一ID")
    template_name: str = Field(..., description="模板名称")
    slide_count: int = Field(..., description="模板页数")
    status: str = Field(..., description="模板状态")
