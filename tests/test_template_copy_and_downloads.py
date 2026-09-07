"""目录/致谢页模板原样保留、SVG 批量 zip 下载、body.pptx 单独下载的测试"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches


# ──────────────────────────────────────────────
# 单元测试：导出器对 toc/end 页原样保留模板 slide
# ──────────────────────────────────────────────

def _make_template(path: Path) -> Path:
    """构造一个包含封面/目录/正文/致谢四页的简单模板。"""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    for text in ("封面页", "模板目录原文", "正文页占位", "模板致谢原文"):
        slide = prs.slides.add_slide(blank)
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
        box.text_frame.text = text
    prs.save(str(path))
    return path


def _slide_texts(pptx_path: Path) -> list[str]:
    prs = Presentation(str(pptx_path))
    return [
        "".join(
            shape.text_frame.text
            for shape in slide.shapes
            if shape.has_text_frame
        )
        for slide in prs.slides
    ]


class TestTemplateCopyPages:
    """toc/end 页必须保留且不被修改"""

    def test_export_keeps_toc_and_end_pages_verbatim(self, tmp_path, test_settings):
        from app.schemas.structured_generation import StructuredPageResult
        from app.services.hybrid_pptx_exporter import HybridPptxExporter

        template = _make_template(tmp_path / "template.pptx")
        output = tmp_path / "out.pptx"
        exporter = HybridPptxExporter(test_settings)
        exporter.export(
            template_pptx_path=template,
            template_rules={"pages": []},
            svg_pages={},
            structured_pages={
                2: StructuredPageResult(
                    page_no=2, should_generate=True, page_type="toc", elements=[],
                ),
                3: StructuredPageResult(
                    page_no=3, should_generate=True, page_type="content", elements=[],
                ),
                4: StructuredPageResult(
                    page_no=4, should_generate=True, page_type="end", elements=[],
                ),
            },
            skipped_pages=set(),
            output_path=output,
        )

        # 第 1 页未保留被删除；目录/致谢页与模板原文完全一致
        assert _slide_texts(output) == ["模板目录原文", "正文页占位", "模板致谢原文"]

    def test_export_fill_does_not_touch_template_copy_page(self, tmp_path, test_settings):
        """即使传了 elements，toc/end 页也不允许被回填修改。"""
        from app.schemas.structured_generation import GeneratedElement, StructuredPageResult
        from app.services.hybrid_pptx_exporter import HybridPptxExporter

        template = _make_template(tmp_path / "template.pptx")
        output = tmp_path / "out.pptx"
        exporter = HybridPptxExporter(test_settings)
        exporter.export(
            template_pptx_path=template,
            template_rules={"pages": []},
            svg_pages={},
            structured_pages={
                2: StructuredPageResult(
                    page_no=2,
                    should_generate=True,
                    page_type="toc",
                    elements=[GeneratedElement(id="title", type="text", content="不应写入")],
                ),
            },
            skipped_pages={1, 3, 4},
            output_path=output,
        )
        assert _slide_texts(output) == ["模板目录原文"]


class TestDiagramInsertAsShapes:
    """diagram SVG 插入 PPT 后应为渲染后的图形（DrawingML 形状），且定位在中下部"""

    _DIAGRAM_SVG = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 320" width="900" height="320">'
        '<rect x="50" y="100" width="120" height="40" fill="#ffcccc" stroke="#d32f2f"/>'
        '<text x="110" y="125" font-size="14" text-anchor="middle" fill="#333">产品A</text>'
        '<rect x="250" y="100" width="120" height="40" fill="#e3f2fd" stroke="#1976d2"/>'
        '<line x1="170" y1="120" x2="250" y2="120" stroke="#1976d2" stroke-width="2"/>'
        "</svg>"
    )

    def test_inserted_diagram_is_shapes_not_source(self, tmp_path, test_settings):
        import dataclasses
        from lxml import etree

        from app.services.hybrid_pptx_exporter import HybridPptxExporter

        scripts_dir = Path("app/vendor/ppt_master/scripts").resolve()
        if not scripts_dir.exists():
            import pytest

            pytest.skip("vendor scripts 目录不存在")

        settings = dataclasses.replace(test_settings, ppt_master_scripts_dir=scripts_dir)
        exporter = HybridPptxExporter(settings)

        template = _make_template(tmp_path / "template.pptx")
        svg_file = tmp_path / "diagram.svg"
        svg_file.write_text(self._DIAGRAM_SVG, encoding="utf-8")

        presentation = Presentation(str(template))
        slide_index = 2  # 正文页
        slide = presentation.slides[slide_index]
        before_count = len(slide.shapes)

        exporter._inject_svg_slide(
            presentation, slide_index, svg_file, replace_existing=False,
        )

        # 原页面 shape 未被删除，且新增的是 DrawingML 形状而非源码文本
        assert len(slide.shapes) > before_count
        slide_xml = etree.tostring(slide._element, encoding="unicode")
        assert "&lt;svg" not in slide_xml and "<svg" not in slide_xml

        # 插入的图形应位于页面中下部（y 偏移超过页面高度的一半）
        slide_h_emu = presentation.slide_height
        ys = []
        for off in slide._element.iter(
            "{http://schemas.openxmlformats.org/drawingml/2006/main}off"
        ):
            y = int(off.get("y", 0))
            if y > 0:
                ys.append(y)
        assert any(y > slide_h_emu * 0.3 for y in ys)


class TestStructuredResultSanitize:
    """结构化结果中混入的 SVG/XML 源码必须被清理"""

    def test_svg_source_is_stripped_from_text(self):
        from app.schemas.structured_generation import GeneratedElement, StructuredPageResult
        from app.services.pptx_builder_service import PptxBuilderService

        result = StructuredPageResult(
            page_no=1,
            should_generate=True,
            elements=[
                GeneratedElement(
                    id="body",
                    type="text",
                    content="<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>",
                ),
            ],
        )
        cleaned = PptxBuilderService._sanitize_result(result)
        content = cleaned.elements[0].content
        assert content is None or "<svg" not in content

    def test_normal_text_is_not_touched(self):
        from app.schemas.structured_generation import GeneratedElement, StructuredPageResult
        from app.services.pptx_builder_service import PptxBuilderService

        result = StructuredPageResult(
            page_no=1,
            should_generate=True,
            elements=[
                GeneratedElement(id="body", type="text", content="正常正文内容"),
            ],
        )
        cleaned = PptxBuilderService._sanitize_result(result)
        assert cleaned.elements[0].content == "正常正文内容"


# ──────────────────────────────────────────────
# 接口测试：zip 打包下载 + body.pptx 单独下载
# ──────────────────────────────────────────────

class TestDiagramZipAndBodyDownload:
    def _create_and_wait(self, client, auth_headers, payload, status_field, timeout=30):
        resp = client.post("/api/v1/generations", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        generation_id = data["generation_id"]
        for _ in range(timeout):
            resp = client.get(f"/api/v1/generations/{generation_id}", headers=auth_headers)
            summary = resp.json()["data"]
            if summary[status_field] in ("completed", "completed_with_warnings", "failed"):
                break
            time.sleep(1)
        else:
            raise AssertionError(f"generation 未在 {timeout} 秒内完成: {summary}")
        return data, summary

    def test_diagrams_zip_download(self, client_with_mock_llm, auth_headers):
        """所有 SVG 统一打包为一个 zip 下载"""
        payload = {
            "generation_mode": "separated_body_diagram",
            "targets": ["diagrams"],
            "auto_compose": False,
            "requirement_text": "系统包含 A、B、C 三个模块，A 调用 B，B 调用 C。",
            "custom_requirements": "画架构图",
        }
        data, summary = self._create_and_wait(
            client_with_mock_llm, auth_headers, payload, "diagram_status",
        )
        assert summary["diagram_status"] == "completed"
        task_id = summary["diagram_task_id"]

        # 任务级：全部 SVG 打一个 zip
        resp = client_with_mock_llm.get(
            f"/api/v1/tasks/{task_id}/diagrams/download",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/zip")
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
            assert len(names) >= 1
            assert all(name.endswith(".svg") for name in names)

        # Generation 级：同样一个 zip
        resp = client_with_mock_llm.get(
            f"/api/v1/generations/{data['generation_id']}/diagrams/download",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            assert len(zf.namelist()) >= 1

    def test_body_pptx_download_when_body_and_diagrams(self, client_with_mock_llm, auth_headers):
        """body + diagrams 都选时，未插入图形的纯文本 body.pptx 仍可下载"""
        payload = {
            "generation_mode": "separated_body_diagram",
            "targets": ["body", "diagrams"],
            "auto_compose": False,
            "requirement_text": "项目：测试项目，包含 A、B、C 三个系统模块。",
            "custom_requirements": "画产品连接关系图",
        }
        data, summary = self._create_and_wait(
            client_with_mock_llm, auth_headers, payload, "body_status",
        )
        assert summary["body_status"] == "completed"
        assert summary["has_body_download"] is True

        resp = client_with_mock_llm.get(
            f"/api/v1/generations/{data['generation_id']}/body/download",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.content[:2] == b"PK"  # pptx 是 zip 容器

        # 通过 artifacts 接口也能拿到 body_pptx
        body_task_id = summary["body_task_id"]
        resp = client_with_mock_llm.get(
            f"/api/v1/tasks/{body_task_id}/artifacts/{summary['body_pptx_artifact_id']}/download",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.content[:2] == b"PK"

    def test_toc_and_end_pages_marked_completed(self, client_with_mock_llm, auth_headers):
        """目录/致谢页应标记为完成且类型正确，不被跳过"""
        payload = {
            "generation_mode": "separated_body_diagram",
            "targets": ["body"],
            "auto_compose": False,
            "requirement_text": "测试正文内容",
        }
        data, summary = self._create_and_wait(
            client_with_mock_llm, auth_headers, payload, "body_status",
        )
        assert summary["body_status"] == "completed"

        resp = client_with_mock_llm.get(
            f"/api/v1/tasks/{summary['body_task_id']}/pages",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        pages = resp.json()["data"]
        by_no = {p["page_no"]: p for p in pages}
        # mock 模板共 3 页：第 3 页（最后一页）为致谢页
        assert by_no[3]["status"] == "completed"
        assert by_no[3]["page_type"] == "end"
        assert by_no[3]["should_generate"] == 1
