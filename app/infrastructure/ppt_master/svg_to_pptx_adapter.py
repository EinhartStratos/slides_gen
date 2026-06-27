from __future__ import annotations

from pathlib import Path
import sys

from app.core.config import Settings


class SvgToPptxAdapter:
    def __init__(self, settings: Settings) -> None:
        scripts_dir = settings.ppt_master_scripts_dir
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from svg_to_pptx.pptx_builder import create_pptx_with_native_svg

        self._create_pptx_with_native_svg = create_pptx_with_native_svg

    def export(self, svg_files: list[Path], output_path: Path) -> bool:
        return bool(
            self._create_pptx_with_native_svg(
                svg_files=svg_files,
                output_path=output_path,
                verbose=False,
                transition=None,
                use_compat_mode=False,
                use_native_shapes=True,
                enable_notes=False,
            )
        )
