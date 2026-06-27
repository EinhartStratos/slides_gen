from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings


@dataclass(slots=True)
class TemplateWorkspace:
    root: Path
    source_dir: Path
    source_pptx: Path
    imported_dir: Path
    imported_svg_dir: Path
    imported_svg_flat_dir: Path
    assets_dir: Path
    manifest_dir: Path
    manifest_path: Path


@dataclass(slots=True)
class TaskWorkspace:
    root: Path
    request_dir: Path
    request_json_path: Path
    input_dir: Path
    requirement_path: Path
    template_snapshot_dir: Path
    template_snapshot_svg_flat_dir: Path
    template_snapshot_assets_dir: Path
    analysis_dir: Path
    svg_output_dir: Path
    svg_final_dir: Path
    validation_dir: Path
    exports_dir: Path
    assets_dir: Path
    result_pptx_path: Path


class ProjectWorkspace:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.runtime_dir = settings.runtime_dir

    def ensure_runtime_dirs(self) -> None:
        for path in [
            self.runtime_dir,
            self.runtime_dir / "templates",
            self.runtime_dir / "tasks",
            self.runtime_dir / "temp",
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def template(self, template_id: str) -> TemplateWorkspace:
        root = self.runtime_dir / "templates" / template_id
        return TemplateWorkspace(
            root=root,
            source_dir=root / "source",
            source_pptx=root / "source" / "template.pptx",
            imported_dir=root / "imported",
            imported_svg_dir=root / "imported" / "svg",
            imported_svg_flat_dir=root / "imported" / "svg-flat",
            assets_dir=root / "imported" / "assets",
            manifest_dir=root / "manifest",
            manifest_path=root / "manifest" / "template_manifest.json",
        )

    def task(self, task_id: str) -> TaskWorkspace:
        root = self.runtime_dir / "tasks" / task_id
        return TaskWorkspace(
            root=root,
            request_dir=root / "request",
            request_json_path=root / "request" / "request.json",
            input_dir=root / "input",
            requirement_path=root / "input" / "requirement.md",
            template_snapshot_dir=root / "template_snapshot",
            template_snapshot_svg_flat_dir=root / "template_snapshot" / "svg-flat",
            template_snapshot_assets_dir=root / "template_snapshot" / "assets",
            analysis_dir=root / "analysis",
            svg_output_dir=root / "svg_output",
            svg_final_dir=root / "svg_final",
            validation_dir=root / "validation",
            exports_dir=root / "exports",
            assets_dir=root / "assets",
            result_pptx_path=root / "exports" / "generated.pptx",
        )

    def ensure_template_dirs(self, workspace: TemplateWorkspace) -> None:
        for path in [
            workspace.root,
            workspace.source_dir,
            workspace.imported_dir,
            workspace.imported_svg_dir,
            workspace.imported_svg_flat_dir,
            workspace.assets_dir,
            workspace.manifest_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def ensure_task_dirs(self, workspace: TaskWorkspace) -> None:
        for path in [
            workspace.root,
            workspace.request_dir,
            workspace.input_dir,
            workspace.template_snapshot_dir,
            workspace.template_snapshot_svg_flat_dir,
            workspace.template_snapshot_assets_dir,
            workspace.analysis_dir,
            workspace.svg_output_dir,
            workspace.svg_final_dir,
            workspace.validation_dir,
            workspace.exports_dir,
            workspace.assets_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)
