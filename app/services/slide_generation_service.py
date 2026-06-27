from __future__ import annotations

from pathlib import Path
import json
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
            "text_replacements": [],
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
        self._apply_generation_metadata(root, ns, analysis)
        self._apply_text_replacements(root, ns, analysis)
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

    def _apply_text_replacements(self, root: ET.Element, ns: str, analysis: dict) -> None:
        replacements = analysis.get("text_replacements") or []
        if not replacements:
            return
        replacement_map: dict[str, str] = {}
        for item in replacements:
            if isinstance(item, dict):
                original = str(item.get("original_text", "")).strip()
                new_text = str(item.get("new_text", "")).strip()
                if original and original != new_text:
                    replacement_map[original] = new_text
        if not replacement_map:
            return
        text_tag = self._svg_tag(ns, "text")
        tspan_tag = self._svg_tag(ns, "tspan")
        for text_el in root.iter(text_tag):
            tspans = list(text_el.iter(tspan_tag))
            if tspans:
                full_text = "".join(t.text or "" for t in tspans).strip()
                if full_text in replacement_map:
                    tspans[0].text = replacement_map[full_text]
                    for extra in tspans[1:]:
                        extra.text = ""
                    continue
                for tspan in tspans:
                    tspan_text = (tspan.text or "").strip()
                    if tspan_text in replacement_map:
                        tspan.text = replacement_map[tspan_text]
            else:
                direct_text = (text_el.text or "").strip()
                if direct_text in replacement_map:
                    text_el.text = replacement_map[direct_text]

    @staticmethod
    def _fmt(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")
