from __future__ import annotations

from pathlib import Path
import json
from xml.etree import ElementTree as ET

from app.infrastructure.llm.base import BasePageGenerationClient
from app.infrastructure.ppt_master.project_workspace import TaskWorkspace


class SlideGenerationService:
    def __init__(self, generation_client: BasePageGenerationClient | None = None) -> None:
        self.generation_client = generation_client

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

    def generate_page_content(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        source_svg_path: Path,
    ) -> dict:
        svg_content = source_svg_path.read_text(encoding="utf-8", errors="ignore")
        if self.generation_client is not None:
            result = self.generation_client.generate_page_svg(
                api_key=api_key,
                requirement_text=requirement_text,
                page_no=page_no,
                page_name=source_svg_path.stem,
                svg_content=svg_content,
            )
            return result.model_dump(mode="json")
        return {
            "page_no": page_no,
            "page_name": source_svg_path.stem,
            "should_generate": True,
            "skip_reason": "",
            "decision_source": "heuristic",
            "generated_svg": None,
            "raw_response_text": None,
        }

    def write_analysis(self, workspace: TaskWorkspace, page_no: int, analysis: dict) -> Path:
        output_path = workspace.analysis_dir / f"page_{page_no:02d}.json"
        output_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    def generate_page(self, source_svg_path: Path, output_svg_path: Path, final_svg_path: Path, analysis: dict) -> tuple[Path, Path]:
        output_svg_path.parent.mkdir(parents=True, exist_ok=True)
        final_svg_path.parent.mkdir(parents=True, exist_ok=True)

        generated_svg = analysis.get("generated_svg")
        if generated_svg:
            output_svg_path.write_text(generated_svg, encoding="utf-8")
        else:
            source_svg_path_bytes = source_svg_path.read_bytes()
            output_svg_path.write_bytes(source_svg_path_bytes)

        self._apply_metadata(output_svg_path, analysis)
        final_svg_path.write_bytes(output_svg_path.read_bytes())
        return output_svg_path, final_svg_path

    @staticmethod
    def _apply_metadata(svg_path: Path, analysis: dict) -> None:
        tree = ET.parse(svg_path)
        root = tree.getroot()
        ns = ""
        if root.tag.startswith("{") and "}" in root.tag:
            ns = root.tag[1:].split("}", 1)[0]
        root.set("data-generated", "true")
        root.set("data-gen-source", str(analysis.get("decision_source") or "heuristic"))
        metadata_tag = f"{{{ns}}}metadata" if ns else "metadata"
        metadata = ET.SubElement(root, metadata_tag)
        metadata.text = json.dumps(
            {
                "page_no": analysis.get("page_no"),
                "page_name": analysis.get("page_name"),
                "should_generate": analysis.get("should_generate", True),
                "skip_reason": analysis.get("skip_reason", ""),
                "decision_source": analysis.get("decision_source", "heuristic"),
            },
            ensure_ascii=False,
        )
        tree.write(svg_path, encoding="utf-8", xml_declaration=True)
