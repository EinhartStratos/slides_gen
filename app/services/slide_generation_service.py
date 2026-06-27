from __future__ import annotations

from pathlib import Path
import json
import textwrap
from xml.etree import ElementTree as ET

from app.infrastructure.llm.base import BasePageAnalysisClient
from app.infrastructure.ppt_master.project_workspace import TaskWorkspace


class SlideGenerationService:
    def __init__(self, analysis_client: BasePageAnalysisClient | None = None) -> None:
        self.analysis_client = analysis_client

    def mirror_assets(self, source_dir: Path, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        if not source_dir.exists():
            return
        for asset_path in source_dir.rglob("*"):
            if not asset_path.is_file():
                continue
            relative = asset_path.relative_to(source_dir)
            destination = target_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(asset_path.read_bytes())

    def analyse_page(self, api_key: str, requirement_text: str, page_no: int, source_svg_path: Path) -> dict:
        if self.analysis_client is not None:
            svg_excerpt = source_svg_path.read_text(encoding="utf-8", errors="ignore")[:4000]
            result = self.analysis_client.analyze_page(
                api_key=api_key,
                requirement_text=requirement_text,
                page_no=page_no,
                page_name=source_svg_path.stem,
                svg_excerpt=svg_excerpt,
            )
            return result.model_dump(mode="json")
        return {
            "page_no": page_no,
            "page_name": source_svg_path.stem,
            "should_generate": True,
            "skip_reason": "",
            "page_title": source_svg_path.stem,
            "page_summary": requirement_text.strip()[:120],
            "bullet_points": [],
            "diagram_kind": None,
            "decision_source": "template_reuse_v1",
            "requirement_length": len(requirement_text.strip()),
        }

    def write_analysis(self, workspace: TaskWorkspace, page_no: int, analysis: dict) -> Path:
        output_path = workspace.analysis_dir / f"page_{page_no:02d}.json"
        output_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    def generate_page(self, source_svg_path: Path, output_svg_path: Path, final_svg_path: Path, analysis: dict) -> tuple[Path, Path]:
        output_svg_path.parent.mkdir(parents=True, exist_ok=True)
        final_svg_path.parent.mkdir(parents=True, exist_ok=True)
        tree = ET.parse(source_svg_path)
        root = tree.getroot()
        ns = self._svg_namespace(root)
        width, height = self._canvas_size(root)
        self._apply_generation_metadata(root, ns, analysis)
        self._append_generated_content(root, ns, width, height, analysis)
        tree.write(output_svg_path, encoding="utf-8", xml_declaration=True)
        final_svg_path.write_bytes(output_svg_path.read_bytes())
        return output_svg_path, final_svg_path

    @staticmethod
    def _svg_namespace(root: ET.Element) -> str:
        if root.tag.startswith("{") and "}" in root.tag:
            return root.tag[1:].split("}", 1)[0]
        return ""

    @staticmethod
    def _svg_tag(ns: str, tag_name: str) -> str:
        return f"{{{ns}}}{tag_name}" if ns else tag_name

    def _canvas_size(self, root: ET.Element) -> tuple[float, float]:
        view_box = root.attrib.get("viewBox", "").replace(",", " ").split()
        if len(view_box) == 4:
            try:
                return float(view_box[2]), float(view_box[3])
            except ValueError:
                pass
        width = self._parse_numeric(root.attrib.get("width"), 1280.0)
        height = self._parse_numeric(root.attrib.get("height"), 720.0)
        return width, height

    @staticmethod
    def _parse_numeric(raw: str | None, default: float) -> float:
        if not raw:
            return default
        filtered = "".join(ch for ch in raw if ch.isdigit() or ch in {".", "-"})
        if not filtered:
            return default
        try:
            return float(filtered)
        except ValueError:
            return default

    def _apply_generation_metadata(self, root: ET.Element, ns: str, analysis: dict) -> None:
        root.set("data-generated", "true")
        root.set("data-gen-source", str(analysis.get("decision_source") or "heuristic"))
        if analysis.get("diagram_kind"):
            root.set("data-gen-kind", str(analysis.get("diagram_kind")))
        metadata = ET.SubElement(root, self._svg_tag(ns, "metadata"))
        metadata.text = json.dumps(
            {
                "page_no": analysis.get("page_no"),
                "page_name": analysis.get("page_name"),
                "should_generate": analysis.get("should_generate", True),
                "skip_reason": analysis.get("skip_reason", ""),
                "page_title": analysis.get("page_title", ""),
                "page_summary": analysis.get("page_summary", ""),
                "bullet_points": analysis.get("bullet_points", []),
                "diagram_kind": analysis.get("diagram_kind"),
                "decision_source": analysis.get("decision_source", "heuristic"),
            },
            ensure_ascii=False,
        )

    def _append_generated_content(self, root: ET.Element, ns: str, width: float, height: float, analysis: dict) -> None:
        title = str(analysis.get("page_title") or analysis.get("page_name") or "")
        summary = str(analysis.get("page_summary") or "")
        bullet_points = [str(item).strip() for item in analysis.get("bullet_points", []) if str(item).strip()]
        if not title and not summary and not bullet_points:
            return
        margin_x = max(width * 0.05, 32)
        panel_width = max(width - margin_x * 2, 240)
        panel_height = min(max(height * 0.24, 120), 220)
        panel_y = max(height - panel_height - margin_x, margin_x)
        group = ET.SubElement(
            root,
            self._svg_tag(ns, "g"),
            {
                "id": "generated-content-group",
                "data-gen-editable": "true",
                "data-gen-source": str(analysis.get("decision_source") or "heuristic"),
            },
        )
        ET.SubElement(
            group,
            self._svg_tag(ns, "rect"),
            {
                "id": "generated-content-panel",
                "x": self._fmt(margin_x),
                "y": self._fmt(panel_y),
                "width": self._fmt(panel_width),
                "height": self._fmt(panel_height),
                "rx": "16",
                "fill": "#FFFFFF",
                "fill-opacity": "0.94",
                "stroke": "#D0D7DE",
                "stroke-width": "1.5",
            },
        )
        cursor_y = panel_y + 30
        if title:
            title_el = ET.SubElement(
                group,
                self._svg_tag(ns, "text"),
                {
                    "id": "generated-title",
                    "x": self._fmt(margin_x + 18),
                    "y": self._fmt(cursor_y),
                    "font-size": "22",
                    "font-weight": "700",
                    "fill": "#111827",
                },
            )
            title_el.text = title[:48]
            cursor_y += 28
        if summary:
            summary_lines = textwrap.wrap(summary, width=34)[:2]
            for idx, line in enumerate(summary_lines, start=1):
                summary_el = ET.SubElement(
                    group,
                    self._svg_tag(ns, "text"),
                    {
                        "id": f"generated-summary-{idx}",
                        "x": self._fmt(margin_x + 18),
                        "y": self._fmt(cursor_y),
                        "font-size": "16",
                        "fill": "#374151",
                    },
                )
                summary_el.text = line
                cursor_y += 22
        for idx, bullet in enumerate(bullet_points[:3], start=1):
            bullet_lines = textwrap.wrap(bullet, width=30)[:2]
            for sub_idx, line in enumerate(bullet_lines, start=1):
                bullet_el = ET.SubElement(
                    group,
                    self._svg_tag(ns, "text"),
                    {
                        "id": f"generated-bullet-{idx}-{sub_idx}",
                        "x": self._fmt(margin_x + 28),
                        "y": self._fmt(cursor_y),
                        "font-size": "15",
                        "fill": "#1F2937",
                    },
                )
                bullet_el.text = f"• {line}" if sub_idx == 1 else f"  {line}"
                cursor_y += 20

    @staticmethod
    def _fmt(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")
