"""业务反馈修复的回归测试。

覆盖：
- 导出器拆页错位修复（拆页 slide 追加到末尾 + 重排，尾页/目录页固定不丢）
- 封面/标题保格式回填（正文/表格仍写死字体）
- 需求文本分块：JSON 信封 + 裸 content 内容嗅探 + 预评估表识别
- 预评估表程序解析（合并单元格、页脚、行语义）
- 章节级上下文路由
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from app.core.config import Settings
from app.infrastructure.ppt_master.pptx_builder import PPTBuilder
from app.schemas.structured_generation import GeneratedElement, StructuredPageResult
from app.services.hybrid_pptx_exporter import HybridPptxExporter
from app.services.requirement_preprocessor import (
    RequirementPreprocessor,
    build_scoped_context,
)


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_name="test",
        app_env="test",
        api_prefix="/api/v1",
        runtime_dir=tmp_path / "runtime",
        mock_ftp_dir=tmp_path / "mock_ftp",
        default_template_file=tmp_path / "template.pptx",
        db_host="127.0.0.1",
        db_port=3306,
        db_user="root",
        db_password="",
        db_schema="test",
        ftp_host="",
        ftp_port=21,
        ftp_user="",
        ftp_password="",
        ftp_root_dir="/slides_gen_server",
        mock_ftp_enabled=True,
        default_template_id=None,
        ppt_master_scripts_dir=Path("app/vendor/ppt_master/scripts").resolve(),
        llm_base_url="",
        llm_model="",
        llm_timeout_seconds=120,
        max_llm_concurrency=8,
        llm_rate_limit_max_retries=3,
        llm_rate_limit_base_delay=1.0,
        llm_rate_limit_max_delay=60.0,
        svg_page_types="diagram",
    )


def _add_text_slide(pres: Presentation, text: str) -> int:
    """加一张空白 slide 放一个文本框，返回 shape_id。"""
    slide = pres.slides.add_slide(pres.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(9), Inches(1))
    box.text_frame.text = text
    return box.shape_id


def _slide_texts(pres: Presentation) -> list[str]:
    out = []
    for slide in pres.slides:
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts.append(shape.text_frame.text)
        out.append(" | ".join(texts))
    return out


# ---------------------------------------------------------------------------
# 导出器：拆页错位 + 固定页
# ---------------------------------------------------------------------------


def _build_export_fixture(tmp_path: Path):
    """构造 5 页模板：封面 / 可拆页正文 / 目录 / 待删正文 / 尾页。"""
    pres = Presentation()
    sid_cover = _add_text_slide(pres, "项目技术方案汇报")
    sid_body = _add_text_slide(pres, "提示文字")
    sid_toc = _add_text_slide(pres, "目录")
    sid_skip = _add_text_slide(pres, "待删页")
    sid_end = _add_text_slide(pres, "感谢聆听，敬请指正！")
    pptx_path = tmp_path / "template.pptx"
    pres.save(pptx_path)

    template_rules = {
        "template": {"slide_size": {"cx": 12192000, "cy": 6858000}},
        "pages": [
            {
                "page_no": 1, "page_name": "封面", "page_purpose": "cover",
                "elements": [{"id": "t1", "type": "text", "shape_id": sid_cover, "bbox": {"x": 0, "y": 0, "w": 1000, "h": 1000}}],
            },
            {
                "page_no": 2, "page_name": "方案要点", "page_purpose": "text",
                "elements": [{
                    "id": "body", "type": "text", "shape_id": sid_body,
                    "bbox": {"x": 0, "y": 0, "w": 300000, "h": 12700},
                    "content_requirement": "按需求项填写，可分多页",
                    "style": {"font_size": 1400},
                }],
            },
            {"page_no": 3, "page_name": "目录", "page_purpose": "toc", "elements": []},
            {
                "page_no": 4, "page_name": "附录", "page_purpose": "text",
                "elements": [{"id": "x", "type": "text", "shape_id": sid_skip, "bbox": {"x": 0, "y": 0, "w": 1000, "h": 1000}}],
            },
            {"page_no": 5, "page_name": "尾页", "page_purpose": "end", "elements": []},
        ],
    }
    return pptx_path, template_rules


def test_export_split_keeps_order_and_end_page(tmp_path: Path):
    """拆页 slide 追加到末尾再重排：尾部页不丢、顺序正确。"""
    pptx_path, template_rules = _build_export_fixture(tmp_path)
    long_text = "\n".join(f"第{i}条方案要点内容需要详细展开描述" for i in range(30))
    structured_pages = {
        1: StructuredPageResult(
            page_no=1, should_generate=True, page_type="cover",
            elements=[GeneratedElement(id="t1", type="text", content="XX项目技术方案")],
        ),
        2: StructuredPageResult(
            page_no=2, should_generate=True,
            elements=[GeneratedElement(id="body", type="text", content=long_text)],
        ),
        3: StructuredPageResult(page_no=3, should_generate=True, page_type="toc", elements=[]),
        4: StructuredPageResult(page_no=4, should_generate=False, skip_reason="不涉及"),
        5: StructuredPageResult(page_no=5, should_generate=True, page_type="end", elements=[]),
    }
    exporter = HybridPptxExporter(settings=_make_settings(tmp_path))
    out = tmp_path / "out.pptx"
    exporter.export(
        template_pptx_path=pptx_path,
        template_rules=template_rules,
        svg_pages={},
        structured_pages=structured_pages,
        skipped_pages=set(),
        output_path=out,
    )
    pres = Presentation(out)
    texts = _slide_texts(pres)
    # 第2页拆页后必然多于1页；第4页被删除；尾页必须在最后
    assert len(pres.slides) > 4, "拆页未发生，测试前提不成立"
    assert "待删页" not in " ".join(texts)
    assert "感谢聆听，敬请指正！" in texts[-1], f"尾页丢失或位置错误: {texts[-1]}"
    assert "目录" in texts[-2], f"目录页位置错误: {texts[-2]}"
    assert texts[0] == "XX项目技术方案"


def test_export_pinned_pages_survive_skipped(tmp_path: Path):
    """目录/尾页即使在 skipped_pages 中也必须保留（固定页不变量）。"""
    pptx_path, template_rules = _build_export_fixture(tmp_path)
    structured_pages = {
        1: StructuredPageResult(
            page_no=1, should_generate=True, page_type="cover",
            elements=[GeneratedElement(id="t1", type="text", content="XX项目")],
        ),
        2: StructuredPageResult(
            page_no=2, should_generate=True,
            elements=[GeneratedElement(id="body", type="text", content="要点")],
        ),
    }
    exporter = HybridPptxExporter(settings=_make_settings(tmp_path))
    out = tmp_path / "out.pptx"
    exporter.export(
        template_pptx_path=pptx_path,
        template_rules=template_rules,
        svg_pages={},
        structured_pages=structured_pages,
        skipped_pages={3, 5},  # 目录/尾页被误标跳过
        output_path=out,
    )
    texts = _slide_texts(Presentation(out))
    assert any("目录" in t for t in texts), "目录页被错误删除"
    assert any("感谢聆听" in t for t in texts), "尾页被错误删除"
    assert "感谢聆听" in texts[-1]


# ---------------------------------------------------------------------------
# PPTBuilder：保格式回填 vs 写死字体
# ---------------------------------------------------------------------------


def _styled_cover_box(slide):
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1.5))
    box.text_frame.text = "模板标题"
    run = box.text_frame.paragraphs[0].runs[0]
    run.font.size = Pt(44)
    run.font.bold = True
    run.font.name = "微软雅黑"
    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    return box


def test_cover_preserves_template_font(tmp_path: Path):
    """封面文本保格式：44磅/加粗/颜色保留，多行 run 全部生效。"""
    pres = Presentation()
    slide = pres.slides.add_slide(pres.slide_layouts[6])
    box = _styled_cover_box(slide)

    page_rule = {
        "page_purpose": "cover",
        "elements": [{"id": "t", "type": "text", "shape_id": box.shape_id}],
    }
    result = StructuredPageResult(
        page_no=1, should_generate=True, page_type="cover",
        elements=[GeneratedElement(id="t", type="text", content="XX项目技术方案\n副标题行")],
    )
    builder = PPTBuilder(tmp_path / "t.pptx")
    builder.fill_single_slide(pres, 0, page_rule, result)

    runs = box.text_frame.paragraphs[0].runs
    assert len(runs) >= 2, "多行内容应产生多个 run"
    for run in runs:
        assert run.font.size == Pt(44), f"封面字号被改: {run.font.size}"
        assert run.font.bold is True
    # rPr 克隆应保留颜色设置（白色 srgbClr 存在于 rPr XML 中）
    rpr_xml = runs[0]._r.find(qn("a:rPr"))
    assert rpr_xml is not None
    assert "FFFFFF" in rpr_xml.xml.upper()


def test_body_text_still_fixed_font(tmp_path: Path):
    """普通正文仍写死 14 磅（不随模板），封面页才保格式。"""
    pres = Presentation()
    slide = pres.slides.add_slide(pres.slide_layouts[6])
    box = _styled_cover_box(slide)  # 44磅样式文本框，但页面是普通 content 页

    page_rule = {
        "page_purpose": "text",
        "elements": [{"id": "t", "type": "text", "shape_id": box.shape_id}],
    }
    result = StructuredPageResult(
        page_no=1, should_generate=True,
        elements=[GeneratedElement(id="t", type="text", content="正文内容")],
    )
    builder = PPTBuilder(tmp_path / "t.pptx")
    builder.fill_single_slide(pres, 0, page_rule, result)
    run = box.text_frame.paragraphs[0].runs[0]
    assert run.font.size == Pt(14)
    assert run.font.name == "微软雅黑"


def test_title_preserves_format_on_content_page(tmp_path: Path):
    """title 元素在任何页都保格式（标题样式属模板设计）。"""
    pres = Presentation()
    slide = pres.slides.add_slide(pres.slide_layouts[6])
    box = _styled_cover_box(slide)

    page_rule = {
        "page_purpose": "text",
        "elements": [{"id": "title", "type": "title", "shape_id": box.shape_id}],
    }
    result = StructuredPageResult(
        page_no=1, should_generate=True,
        elements=[GeneratedElement(id="title", type="text", content="章节标题")],
    )
    builder = PPTBuilder(tmp_path / "t.pptx")
    builder.fill_single_slide(pres, 0, page_rule, result)
    run = box.text_frame.paragraphs[0].runs[0]
    assert run.font.size == Pt(44)
    assert run.font.bold is True


def test_fill_single_slide_duplicates_appended_at_end(tmp_path: Path):
    """拆页产生的复制 slide 追加到 deck 末尾，不挤占后续页位置。"""
    pres = Presentation()
    sid1 = _add_text_slide(pres, "提示")
    _add_text_slide(pres, "第二页原样")
    _add_text_slide(pres, "第三页原样")

    page_rule = {
        "page_purpose": "text",
        "elements": [{
            "id": "body", "type": "text", "shape_id": sid1,
            "bbox": {"x": 0, "y": 0, "w": 300000, "h": 12700},
            "content_requirement": "可分多页",
            "style": {"font_size": 1400},
        }],
    }
    long_text = "\n".join(f"第{i}条内容展开描述" for i in range(30))
    result = StructuredPageResult(
        page_no=1, should_generate=True,
        elements=[GeneratedElement(id="body", type="text", content=long_text)],
    )
    builder = PPTBuilder(tmp_path / "t.pptx")
    occupied = builder.fill_single_slide(pres, 0, page_rule, result)
    assert len(occupied) > 1, "测试前提：内容应拆页"
    assert occupied[0] == 0
    # 后续 slide 位置不动：索引1/2 仍是原页
    assert "第二页原样" in pres.slides[1].shapes[0].text_frame.text
    assert "第三页原样" in pres.slides[2].shapes[0].text_frame.text
    # 复制页在末尾
    assert sorted(occupied[1:]) == list(range(3, 3 + len(occupied) - 1))


# ---------------------------------------------------------------------------
# 需求文本分块：JSON 信封 + 裸 content + 预评估识别
# ---------------------------------------------------------------------------

_SAMPLE_PX = """sheet-name: 预评估范围
CSV content:
需求项,涉及产品,版本情况,联系人,工作说明,备注,费用合计（万元）,按需求项合计费用（约，万元）,合计费用（约，万元）,主产品,部门,团队,厂商,,,开发&管控（自有）,,开发（外购）,,功能测试（自有）,,功能测试(外购),
,,,,,,,,,,,,工作量,单价,费用（万元）,工作量,费用（万元）,工作量,费用（万元）,工作量,费用（万元）,工作量,费用（万元）
需求项A（功能类）,P-A,有版本,张三,"1.改造点一
2.改造点二",可4月独立批次,#REF!,,,C-MAIN,开发一部,某团队,0,,0,20,4.33,10,1.5,5,1.0,8,1.2
,P-B,配合测试,李四,配合测试,,#REF!,,,C-MAIN,开发一部,某团队,0,,0,5,1.08,0,0,0,0,0,0
需求项B（功能类,P-C,有版本,王五,改造点三,最早2608批次,#REF!,,,C-MAIN,开发二部,某团队,0,,0,10,2.16,5,0.7,2,0.4,3,0.5
项目管理,,,,,,,,,,,,0,,0,5,1.08,0,0,0,0,0,0
费用、工作量合计,,,,,#REF!,#REF!,,,,,0,,0,45,,15,,7,,11,
,,,,,,,,,,,,,,,工作量合计,72
业务联系人：,,,,,,,,,,,,,,,,,
,张一、王二,,,,,,,,,,,,,,,,

sheet-name: 排期意见收集
CSV content:
产品,开发工作量,测试工作量,是否可于四月独立批次实施,

"""


def test_split_chunks_json_envelope():
    """JSON 信封：docx 按文件名分 situation/requirement，xlsx 按 sheet 分类。"""
    doc = {"code": 200, "result": "需求说明书正文", "data": {"type": "docx", "filename": "需求书.docx"}}
    sit = {"code": 200, "result": "项目情况说明正文", "data": {"type": "docx", "filename": "应用项目情况说明.docx"}}
    xls = {"code": 200, "result": _SAMPLE_PX, "data": {"type": "xlsx", "filename": "预评估.xlsx"}}
    raw = json.dumps(doc, ensure_ascii=False) + "\n" + json.dumps(sit, ensure_ascii=False) + "\n" + json.dumps(xls, ensure_ascii=False)
    chunks = RequirementPreprocessor._split_into_chunks(raw)
    assert "需求说明书正文" in chunks["requirement_doc"]
    assert "项目情况说明正文" in chunks["situation_doc"]
    assert "需求说明书正文" in chunks["docx"] and "项目情况说明正文" in chunks["docx"]
    assert "预评估范围" in chunks["pre_eval"] and "排期意见" in chunks["pre_eval"]


def test_split_chunks_bare_content():
    """裸 content（非 JSON）：按内容嗅探分块。"""
    raw = "需求说明书\n需求编号：FR-1\n主办部门：某部门\n\n" + _SAMPLE_PX
    chunks = RequirementPreprocessor._split_into_chunks(raw)
    assert "需求编号" in chunks["requirement_doc"]
    assert "预评估范围" in chunks["pre_eval"]


def test_parse_pre_eval():
    """预评估解析：合并单元格前向填充、行对齐、页脚归类、费用列忽略。"""
    parsed = RequirementPreprocessor._parse_pre_eval(_SAMPLE_PX)
    assert parsed is not None
    names = [i["需求项"] for i in parsed["items"]]
    assert names == ["需求项A", "需求项B", "项目管理"]
    item_a = parsed["items"][0]
    assert len(item_a["rows"]) == 2
    assert item_a["rows"][0]["主产品"] == "C-MAIN"
    assert item_a["rows"][0]["部门"] == "开发一部"
    assert item_a["rows"][0]["开发自有"] == 20
    assert item_a["rows"][1]["版本情况"] == "配合测试"
    # 需求项B 无右括号容错 + 前向填充正常
    assert parsed["items"][1]["原始需求项名"] == "需求项B（功能类"
    # 页脚
    assert parsed["totals"]["工作量合计"] == "72"
    assert "张一" in parsed["contacts"] and "王二" in parsed["contacts"]


def test_pre_eval_to_items_and_matrix():
    """预评估行 → 需求项清单/产品清单：改造 vs 配合测试按版本情况区分。"""
    parsed = RequirementPreprocessor._parse_pre_eval(_SAMPLE_PX)
    items = RequirementPreprocessor._pre_eval_requirement_items(parsed)
    a = items[0]
    assert a["名称"] == "需求项A"
    assert a["改造产品"] == ["P-A"]
    assert a["配合测试产品"] == ["P-B"]
    matrix = RequirementPreprocessor._pre_eval_product_matrix(parsed)
    pa = next(p for p in matrix if p["产品英文"] == "P-A")
    pb = next(p for p in matrix if p["产品英文"] == "P-B")
    assert pa["实施类型"] == "改造" and pa["工作量（人天）"] == 43
    assert pb["实施类型"] == "仅配合测试" and pb["工作量（人天）"] == 5


def test_scoped_context_routing():
    """章节路由：方案要点页命中 pre_eval+situation，未知页返回空。"""
    chunks = {"pre_eval": "预评估内容", "situation_doc": "情况说明内容", "workload": "工作量内容"}
    ctx = build_scoped_context(chunks, "项目方案要点")
    assert "预评估内容" in ctx and "情况说明内容" in ctx
    assert "工作量内容" not in ctx
    assert build_scoped_context(chunks, "不认识的页面") == ""
    assert build_scoped_context(None, "项目方案要点") == ""


def test_workload_chunk_still_parsed():
    """工作量明细 sheet 仍归 workload（'评估'不误伤，预评估优先）。"""
    xls = (
        "sheet-name: 工作量明细\nCSV content:\n序号,需求编号,需求项,产品英文\n1,X,Y,Z\n\n"
        "sheet-name: 预评估范围\nCSV content:\n需求项,涉及产品\nA,B\n\n"
    )
    chunks = RequirementPreprocessor._split_into_chunks(xls)
    assert "工作量明细" in chunks["workload"]
    assert "预评估范围" in chunks["pre_eval"]
    assert "预评估" not in chunks["workload"]
