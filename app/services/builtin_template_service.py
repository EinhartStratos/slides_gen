from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings
from app.core.constants import TEMPLATE_STATUS_READY
from app.core.exceptions import NotFoundError
from app.infrastructure.db.template_repository import TemplateRepository
from app.services.template_import_service import TemplateImportService


class BuiltinTemplateService:
    def __init__(
        self,
        settings: Settings,
        repository: TemplateRepository,
        template_import_service: TemplateImportService,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.template_import_service = template_import_service

    def ensure_default_template(self) -> dict:
        configured_template_id = self.settings.default_template_id
        if configured_template_id:
            template = self.repository.get_by_id(configured_template_id)
            if template is not None and template.get("status") == TEMPLATE_STATUS_READY:
                return template
        builtin_template = self.repository.get_latest_builtin()
        if builtin_template is not None:
            return builtin_template
        template_path = self.settings.default_template_file
        if not template_path.exists():
            raise NotFoundError(f"默认模板文件不存在: {template_path}")
        imported = self.template_import_service.import_local_template(
            template_name=template_path.stem or "default_template",
            template_path=template_path,
            is_builtin=True,
        )
        return imported

    async def import_builtin_template(self, template_name: str | None = None, template_file: UploadFile | None = None) -> dict:
        if template_file is not None:
            content = await template_file.read()
            return self.template_import_service.import_template_bytes(
                api_key=None,
                template_name=template_name or Path(template_file.filename or "builtin_template.pptx").stem,
                source_filename=template_file.filename or "builtin_template.pptx",
                content=content,
                source_type="builtin",
                is_builtin=True,
            )
        if template_name is None:
            return self.ensure_default_template()
        template_path = self.settings.default_template_file
        if not template_path.exists():
            raise NotFoundError(f"默认模板文件不存在: {template_path}")
        return self.template_import_service.import_local_template(
            template_name=template_name or template_path.stem or "default_template",
            template_path=template_path,
            is_builtin=True,
        )
