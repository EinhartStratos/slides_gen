from __future__ import annotations

from pathlib import Path
import sys

from app.core.config import Settings


class PptxToSvgAdapter:
    def __init__(self, settings: Settings) -> None:
        scripts_dir = settings.ppt_master_scripts_dir
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from pptx_to_svg import convert_pptx_to_svg
        from pptx_to_svg.converter import ConvertOptions

        self._convert_pptx_to_svg = convert_pptx_to_svg
        self._convert_options = ConvertOptions

    def convert(self, pptx_path: Path, output_dir: Path):
        options = self._convert_options(media_subdir="assets", inheritance_mode="both")
        return self._convert_pptx_to_svg(pptx_path, output_dir, options)
