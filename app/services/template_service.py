from __future__ import annotations

from pathlib import Path
import shutil

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.utils import to_iso
from app.infrastructure.db.template_repository import TemplateRepository
from app.infrastructure.ppt_master.pptx_to_svg_adapter import PptxToSvgAdapter
from app.infrastructure.ppt_master.project_workspace import ProjectWorkspace, TemplateWorkspace
from app.infrastructure.storage.ftp import FtpStorage


class TemplateService:
    def __init__(
        self,
        repository: TemplateRepository,
        workspace: ProjectWorkspace,
        ftp: FtpStorage,
        pptx_to_svg: PptxToSvgAdapter,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.ftp = ftp
        self.pptx_to_svg = pptx_to_svg

    def get_template(self, template_id: str) -> dict:
        template = self.repository.get_by_id(template_id)
        if template is None:
            raise NotFoundError(f"模板不存在: {template_id}")
        return template

    def get_accessible_template(self, api_key: str | None, template_id: str) -> dict:
        template = self.repository.get_by_id(template_id)
        if template is None:
            raise NotFoundError(f"模板不存在: {template_id}")
        if template.get("api_key") not in {None, api_key} and not bool(template.get("is_builtin")):
            raise ForbiddenError("无权访问该模板")
        return template

    def list_templates(self, api_key: str | None) -> list[dict]:
        return self.repository.list_for_api_key(api_key)

    def serialize_summary(self, template: dict) -> dict:
        return {
            "template_id": template["template_id"],
            "template_name": template["template_name"],
            "source_type": template.get("source_type"),
            "source_filename": template.get("source_filename"),
            "slide_count": template.get("slide_count"),
            "status": template.get("status"),
            "is_builtin": bool(template.get("is_builtin")),
            "created_at": to_iso(template.get("created_at")),
        }

    def serialize_detail(self, template: dict) -> dict:
        return {
            **self.serialize_summary(template),
            "source_ftp_path": template.get("source_ftp_path"),
            "imported_svg_dir_ftp_path": template.get("imported_svg_dir_ftp_path"),
            "imported_svg_flat_dir_ftp_path": template.get("imported_svg_flat_dir_ftp_path"),
            "assets_ftp_dir_path": template.get("assets_ftp_dir_path"),
            "manifest_ftp_path": template.get("manifest_ftp_path"),
        }

    def serialize_import_result(self, template: dict) -> dict:
        return {
            "template_id": template["template_id"],
            "template_name": template["template_name"],
            "slide_count": int(template.get("slide_count") or 0),
            "status": template.get("status"),
        }

    def ensure_local_template_workspace(self, template: dict) -> TemplateWorkspace:
        template_id = str(template["template_id"])
        workspace = self.workspace.template(template_id)
        self.workspace.ensure_template_dirs(workspace)
        if workspace.imported_svg_dir.exists() and any(workspace.imported_svg_dir.rglob("*.svg")):
            return workspace
        source_ftp_path = template.get("source_ftp_path")
        if not source_ftp_path:
            raise NotFoundError(f"模板缺少源文件路径: {template_id}")
        self.ftp.download_file(str(source_ftp_path), workspace.source_pptx)
        result = self.pptx_to_svg.convert(workspace.source_pptx, workspace.imported_dir)
        manifest = {
            "template_id": template_id,
            "template_name": template.get("template_name"),
            "slide_count": len(getattr(result, "slides", []) or []),
        }
        workspace.manifest_path.write_text(str(manifest), encoding="utf-8")
        return workspace

    def copy_flat_svgs_to_task_snapshot(self, template: dict, target_dir: Path, assets_target_dir: Path) -> list[Path]:
        workspace = self.ensure_local_template_workspace(template)
        target_dir.mkdir(parents=True, exist_ok=True)
        assets_target_dir.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []
        for svg_path in sorted(workspace.imported_svg_flat_dir.glob("*.svg")):
            target_path = target_dir / svg_path.name
            shutil.copy2(svg_path, target_path)
            copied.append(target_path)
        if workspace.assets_dir.exists():
            for asset_path in workspace.assets_dir.rglob("*"):
                if not asset_path.is_file():
                    continue
                relative = asset_path.relative_to(workspace.assets_dir)
                destination = assets_target_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(asset_path, destination)
        return copied
