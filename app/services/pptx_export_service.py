from __future__ import annotations

from pathlib import Path

from app.core.exceptions import ConflictError
from app.infrastructure.ppt_master.svg_to_pptx_adapter import SvgToPptxAdapter


class PptxExportService:
    def __init__(self, adapter: SvgToPptxAdapter) -> None:
        self.adapter = adapter

    def export(self, svg_final_dir: Path, output_path: Path) -> Path:
        svg_files = sorted(svg_final_dir.glob("*.svg"))
        if not svg_files:
            raise ConflictError("当前没有可导出的最终 SVG 页面")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        success = self.adapter.export(svg_files, output_path)
        if not success or not output_path.exists():
            raise RuntimeError("svg_to_pptx 导出失败")
        return output_path
