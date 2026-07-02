"""幻灯片生成服务测试"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.infrastructure.llm.base import PagePlanResult, PageGenerationResult
from app.infrastructure.ppt_master.project_workspace import ProjectWorkspace
from app.services.slide_generation_service import SlideGenerationService


def make_project_workspace(tmp_path) -> ProjectWorkspace:
    settings = Settings(
        app_name="test",
        app_env="test",
        api_prefix="/api/v1",
        runtime_dir=tmp_path / "runtime",
        mock_ftp_dir=tmp_path / "mock_ftp",
        default_template_file=tmp_path / "templete.pptx",
        db_host="",
        db_port=3306,
        db_user="",
        db_password="",
        db_schema="",
        ftp_host="",
        ftp_port=21,
        ftp_user="",
        ftp_password="",
        ftp_root_dir="/slides_gen_server",
        mock_ftp_enabled=True,
        default_template_id=None,
        ppt_master_scripts_dir=tmp_path / "scripts",
        llm_base_url="",
        llm_model="",
        llm_timeout_seconds=10,
        max_llm_concurrency=4,
        llm_rate_limit_max_retries=3,
        llm_rate_limit_base_delay=0.1,
        llm_rate_limit_max_delay=1.0,
        svg_page_types="diagram",
    )
    pw = ProjectWorkspace(settings)
    pw.ensure_runtime_dirs()
    return pw


class TestPlanPagesWithoutClient:
    """无 LLM 客户端时的启发式规划"""

    def test_heuristic_plan_cover(self, tmp_path):
        svg = tmp_path / "slide_1.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        service = SlideGenerationService(generation_client=None)
        plans = service.plan_pages("key", "需求", [svg])
        assert plans[0]["page_type"] == "cover"
        assert plans[0]["decision_source"] == "heuristic"
        assert plans[0]["should_generate"] is True

    def test_heuristic_plan_end(self, tmp_path):
        svgs = []
        for i in range(1, 4):
            svg = tmp_path / f"slide_{i}.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
            svgs.append(svg)
        service = SlideGenerationService(generation_client=None)
        plans = service.plan_pages("key", "需求", svgs)
        assert plans[-1]["page_type"] == "end"

    def test_heuristic_plan_toc(self, tmp_path):
        svg1 = tmp_path / "slide_1.svg"
        svg1.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        svg2 = tmp_path / "目录.svg"
        svg2.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        svg3 = tmp_path / "slide_3.svg"
        svg3.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        service = SlideGenerationService(generation_client=None)
        plans = service.plan_pages("key", "需求", [svg1, svg2, svg3])
        assert plans[1]["page_type"] == "toc"

    def test_heuristic_plan_diagram(self, tmp_path):
        svg1 = tmp_path / "slide_1.svg"
        svg1.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        svg2 = tmp_path / "系统架构图.svg"
        svg2.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        svg3 = tmp_path / "slide_3.svg"
        svg3.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        service = SlideGenerationService(generation_client=None)
        plans = service.plan_pages("key", "需求", [svg1, svg2, svg3])
        assert plans[1]["page_type"] == "diagram"


class TestPlanPagesWithClient:
    """有 LLM 客户端时的规划"""

    def test_llm_plan_called_with_model_params(self, tmp_path):
        svg = tmp_path / "slide_1.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        mock_client = MagicMock()
        mock_client.plan_single_page.return_value = PagePlanResult(
            page_no=1, page_name="slide_1", should_generate=True, page_type="cover",
            page_title="封面", decision_source="llm",
        )
        service = SlideGenerationService(generation_client=mock_client)
        plans = service.plan_pages("key", "需求", [svg], model="custom-model", enable_thinking=True)

        mock_client.plan_single_page.assert_called_once()
        call_kwargs = mock_client.plan_single_page.call_args
        assert call_kwargs.kwargs["model"] == "custom-model"
        assert call_kwargs.kwargs["enable_thinking"] is True
        assert plans[0]["decision_source"] == "llm"

    def test_llm_plan_default_params(self, tmp_path):
        svg = tmp_path / "slide_1.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        mock_client = MagicMock()
        mock_client.plan_single_page.return_value = PagePlanResult(
            page_no=1, page_name="slide_1", should_generate=True, page_type="content",
            page_title="测试", decision_source="llm",
        )
        service = SlideGenerationService(generation_client=mock_client)
        plans = service.plan_pages("key", "需求", [svg])

        call_kwargs = mock_client.plan_single_page.call_args
        assert call_kwargs.kwargs["model"] is None
        assert call_kwargs.kwargs["enable_thinking"] is False


class TestGeneratePageSvg:
    def test_generate_with_client(self, tmp_path):
        svg = tmp_path / "slide_2.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        mock_client = MagicMock()
        mock_client.generate_page_svg.return_value = PageGenerationResult(
            page_no=2, page_name="slide_2", generated_svg="<svg>generated</svg>",
            decision_source="llm",
        )
        service = SlideGenerationService(generation_client=mock_client)
        result = service.generate_page_svg("key", "需求", 2, svg, {"page_type": "content", "page_title": "测试"})

        assert result["decision_source"] == "llm"
        assert result["generated_svg"] == "<svg>generated</svg>"

    def test_generate_with_model_params(self, tmp_path):
        svg = tmp_path / "slide_2.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        mock_client = MagicMock()
        mock_client.generate_page_svg.return_value = PageGenerationResult(
            page_no=2, page_name="slide_2", generated_svg="<svg/>", decision_source="llm",
        )
        service = SlideGenerationService(generation_client=mock_client)
        service.generate_page_svg(
            "key", "需求", 2, svg, {"page_type": "content", "page_title": "测试"},
            model="my-model", enable_thinking=True,
        )

        call_kwargs = mock_client.generate_page_svg.call_args
        assert call_kwargs.kwargs["model"] == "my-model"
        assert call_kwargs.kwargs["enable_thinking"] is True

    def test_generate_without_client(self, tmp_path):
        svg = tmp_path / "slide_2.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        service = SlideGenerationService(generation_client=None)
        result = service.generate_page_svg("key", "需求", 2, svg, {"page_type": "content", "page_title": "测试"})
        assert result["decision_source"] == "heuristic"
        assert result["generated_svg"] is None


class TestWritePlan:
    def test_write_plan_json(self, tmp_path):
        pw = make_project_workspace(tmp_path)
        workspace = pw.task("task_001")
        pw.ensure_task_dirs(workspace)
        service = SlideGenerationService()
        plans = [{"page_no": 1, "page_type": "cover"}]
        path = service.write_plan(workspace, plans)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data[0]["page_no"] == 1


class TestWritePageResult:
    def test_write_page_result_json(self, tmp_path):
        pw = make_project_workspace(tmp_path)
        workspace = pw.task("task_001")
        pw.ensure_task_dirs(workspace)
        service = SlideGenerationService()
        result = {"page_no": 1, "decision_source": "llm"}
        path = service.write_page_result(workspace, 1, result)
        assert path.exists()
        assert "page_01.json" in path.name


class TestRenderPage:
    def test_render_with_generated_svg(self, tmp_path):
        source = tmp_path / "source.svg"
        source.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        output = tmp_path / "output" / "source.svg"
        final = tmp_path / "final" / "source.svg"
        service = SlideGenerationService()
        page_result = {"generated_svg": '<svg xmlns="http://www.w3.org/2000/svg"><text>hi</text></svg>', "page_no": 1, "decision_source": "llm"}
        out_path, final_path = service.render_page(source, output, final, page_result)
        assert out_path.exists()
        assert final_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "hi" in content

    def test_render_without_generated_svg_copies_source(self, tmp_path):
        source = tmp_path / "source.svg"
        source.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>original</text></svg>', encoding="utf-8")
        output = tmp_path / "output" / "source.svg"
        final = tmp_path / "final" / "source.svg"
        service = SlideGenerationService()
        page_result = {"generated_svg": None, "page_no": 1, "decision_source": "heuristic"}
        out_path, final_path = service.render_page(source, output, final, page_result)
        content = out_path.read_text(encoding="utf-8")
        assert "original" in content
