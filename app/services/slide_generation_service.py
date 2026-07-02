from __future__ import annotations

from pathlib import Path
import json
import logging
from xml.etree import ElementTree as ET

from app.infrastructure.llm.base import BasePageGenerationClient
from app.infrastructure.ppt_master.project_workspace import TaskWorkspace


logger = logging.getLogger(__name__)


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

    def plan_pages(
        self,
        api_key: str,
        requirement_text: str,
        source_svgs: list[Path],
        model: str | None = None,
        enable_thinking: bool = False,
    ) -> list[dict]:
        total_pages = len(source_svgs)
        results: list[dict] = []
        for i, svg_path in enumerate(source_svgs, start=1):
            page_name = svg_path.stem
            svg_content = svg_path.read_text(encoding="utf-8", errors="ignore")
            result = self.plan_single_page(
                api_key=api_key,
                requirement_text=requirement_text,
                page_no=i,
                page_name=page_name,
                svg_content=svg_content,
                total_pages=total_pages,
                model=model,
                enable_thinking=enable_thinking,
            )
            results.append(result)
        return results

    def plan_single_page(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        page_name: str,
        svg_content: str,
        total_pages: int = 0,
        model: str | None = None,
        enable_thinking: bool = False,
    ) -> dict:
        """对单页进行规划，返回 plan dict。"""
        if self.generation_client is not None:
            plan = self.generation_client.plan_single_page(
                api_key=api_key,
                requirement_text=requirement_text,
                page_no=page_no,
                page_name=page_name,
                svg_content=svg_content,
                total_pages=total_pages,
                model=model,
                enable_thinking=enable_thinking,
            )
            return plan.model_dump(mode="json")
        if page_no == 1:
            page_type = "cover"
        elif total_pages > 0 and page_no == total_pages:
            page_type = "end"
        elif "目录" in page_name or "toc" in page_name.lower():
            page_type = "toc"
        elif any(kw in page_name for kw in ["架构", "流程", "时序", "图"]):
            page_type = "diagram"
        else:
            page_type = "content"
        return {
            "page_no": page_no,
            "page_name": page_name,
            "should_generate": True,
            "skip_reason": "",
            "page_type": page_type,
            "page_title": page_name,
            "decision_source": "heuristic",
            "raw_response_text": None,
        }

    def generate_page_svg(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        source_svg_path: Path,
        page_plan: dict,
        model: str | None = None,
        enable_thinking: bool = False,
    ) -> dict:
        svg_content = source_svg_path.read_text(encoding="utf-8", errors="ignore")
        if self.generation_client is not None:
            result = self.generation_client.generate_page_svg(
                api_key=api_key,
                requirement_text=requirement_text,
                page_no=page_no,
                page_name=source_svg_path.stem,
                page_type=page_plan.get("page_type", "content"),
                page_title=page_plan.get("page_title", ""),
                svg_content=svg_content,
                model=model,
                enable_thinking=enable_thinking,
            )
            return result.model_dump(mode="json")
        return {
            "page_no": page_no,
            "page_name": source_svg_path.stem,
            "generated_svg": None,
            "decision_source": "heuristic",
            "raw_response_text": None,
        }

    def write_plan(self, workspace: TaskWorkspace, plans: list[dict]) -> Path:
        output_path = workspace.analysis_dir / "page_plans.json"
        output_path.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    def write_page_result(self, workspace: TaskWorkspace, page_no: int, result: dict) -> Path:
        output_path = workspace.analysis_dir / f"page_{page_no:02d}.json"
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    def render_page(self, source_svg_path: Path, output_svg_path: Path, final_svg_path: Path, page_result: dict) -> tuple[Path, Path]:
        output_svg_path.parent.mkdir(parents=True, exist_ok=True)
        final_svg_path.parent.mkdir(parents=True, exist_ok=True)

        generated_svg = page_result.get("generated_svg")
        if generated_svg:
            output_svg_path.write_text(generated_svg, encoding="utf-8")
        else:
            output_svg_path.write_bytes(source_svg_path.read_bytes())

        self._apply_metadata(output_svg_path, page_result)
        final_svg_path.write_bytes(output_svg_path.read_bytes())
        return output_svg_path, final_svg_path

    @staticmethod
    def _apply_metadata(svg_path: Path, page_result: dict) -> None:
        tree = ET.parse(svg_path)
        root = tree.getroot()
        ns = ""
        if root.tag.startswith("{") and "}" in root.tag:
            ns = root.tag[1:].split("}", 1)[0]
        root.set("data-generated", "true")
        root.set("data-gen-source", str(page_result.get("decision_source") or "heuristic"))
        metadata_tag = f"{{{ns}}}metadata" if ns else "metadata"
        metadata = ET.SubElement(root, metadata_tag)
        metadata.text = json.dumps(
            {
                "page_no": page_result.get("page_no"),
                "page_name": page_result.get("page_name"),
                "decision_source": page_result.get("decision_source", "heuristic"),
            },
            ensure_ascii=False,
        )
        tree.write(svg_path, encoding="utf-8", xml_declaration=True)
