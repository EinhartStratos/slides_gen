from __future__ import annotations

from pathlib import Path
import json

from fastapi import UploadFile

from app.core.constants import TEMPLATE_STATUS_READY
from app.core.utils import generate_id
from app.infrastructure.db.template_repository import TemplateRepository
from app.infrastructure.ppt_master.pptx_to_svg_adapter import PptxToSvgAdapter
from app.infrastructure.ppt_master.project_workspace import ProjectWorkspace
from app.infrastructure.storage.ftp import FtpStorage


class TemplateImportService:
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

    async def import_template(self, api_key: str, template_name: str, template_file: UploadFile) -> dict:
        content = await template_file.read()
        return self.import_template_bytes(
            api_key=api_key,
            template_name=template_name,
            source_filename=template_file.filename or "template.pptx",
            content=content,
            source_type="custom",
            is_builtin=False,
        )

    def import_local_template(self, template_name: str, template_path: Path, is_builtin: bool = False) -> dict:
        return self.import_template_bytes(
            api_key=None,
            template_name=template_name,
            source_filename=template_path.name,
            content=template_path.read_bytes(),
            source_type="builtin" if is_builtin else "custom",
            is_builtin=is_builtin,
        )

    def import_template_bytes(
        self,
        api_key: str | None,
        template_name: str,
        source_filename: str,
        content: bytes,
        source_type: str,
        is_builtin: bool,
    ) -> dict:
        template_id = generate_id("tpl")
        template_workspace = self.workspace.template(template_id)
        self.workspace.ensure_template_dirs(template_workspace)
        template_workspace.source_pptx.write_bytes(content)
        result = self.pptx_to_svg.convert(template_workspace.source_pptx, template_workspace.imported_dir)

        slide_count = len(getattr(result, "slides", []) or [])
        canvas_px = getattr(result, "canvas_px", (0, 0))
        slide_width_emu = int(canvas_px[0] * 9525) if canvas_px else None
        slide_height_emu = int(canvas_px[1] * 9525) if canvas_px else None

        manifest = {
            "template_id": template_id,
            "template_name": template_name,
            "source_filename": source_filename,
            "slide_count": slide_count,
            "canvas_px": list(canvas_px),
            "is_builtin": is_builtin,
        }
        template_workspace.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        remote_root = self.ftp.join(self.ftp.settings.ftp_root_dir, "templates", template_id)
        source_ftp_path = self.ftp.upload_file(template_workspace.source_pptx, self.ftp.join(remote_root, "source", "template.pptx"))
        imported_svg_dir_ftp_path = self.ftp.join(remote_root, "imported", "svg")
        imported_svg_flat_dir_ftp_path = self.ftp.join(remote_root, "imported", "svg-flat")
        assets_ftp_dir_path = self.ftp.join(remote_root, "imported", "assets")
        manifest_ftp_path = self.ftp.upload_file(template_workspace.manifest_path, self.ftp.join(remote_root, "manifest", "template_manifest.json"))

        for path in sorted(template_workspace.imported_svg_dir.rglob("*.svg")):
            relative = path.relative_to(template_workspace.imported_svg_dir).as_posix()
            self.ftp.upload_file(path, self.ftp.join(imported_svg_dir_ftp_path, relative))
        for path in sorted(template_workspace.imported_svg_flat_dir.rglob("*.svg")):
            relative = path.relative_to(template_workspace.imported_svg_flat_dir).as_posix()
            self.ftp.upload_file(path, self.ftp.join(imported_svg_flat_dir_ftp_path, relative))
        if template_workspace.assets_dir.exists():
            for path in sorted(template_workspace.assets_dir.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(template_workspace.assets_dir).as_posix()
                self.ftp.upload_file(path, self.ftp.join(assets_ftp_dir_path, relative))

        self.repository.create(
            {
                "template_id": template_id,
                "api_key": api_key,
                "template_name": template_name,
                "source_type": source_type,
                "source_filename": source_filename,
                "source_ftp_path": source_ftp_path,
                "imported_svg_dir_ftp_path": imported_svg_dir_ftp_path,
                "imported_svg_flat_dir_ftp_path": imported_svg_flat_dir_ftp_path,
                "assets_ftp_dir_path": assets_ftp_dir_path,
                "manifest_ftp_path": manifest_ftp_path,
                "slide_count": slide_count,
                "slide_width_emu": slide_width_emu,
                "slide_height_emu": slide_height_emu,
                "is_builtin": is_builtin,
                "status": TEMPLATE_STATUS_READY,
            }
        )
        created = self.repository.get_by_id(template_id)
        if created is not None:
            return created
        return {
            "template_id": template_id,
            "template_name": template_name,
            "slide_count": slide_count,
            "status": TEMPLATE_STATUS_READY,
            "is_builtin": is_builtin,
        }
