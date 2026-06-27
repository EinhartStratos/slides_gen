from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET


class SvgValidationService:
    def validate(self, svg_path: Path) -> tuple[str, str]:
        try:
            root = ET.parse(svg_path).getroot()
        except Exception as exc:
            return "failed", f"SVG 解析失败: {exc}"
        tag = root.tag.split("}")[-1]
        if tag.lower() != "svg":
            return "failed", "根节点不是 svg"
        return "passed", "ok"
