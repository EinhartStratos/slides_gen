"""结构化生成数据模型和混合导出相关测试"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from app.schemas.structured_generation import (
    BoundingBox,
    GeneratedElement,
    StructuredPageResult,
    TableSchema,
    ElementRule,
    PageRule,
    TemplateMeta,
    SlideSize,
    TemplateRules,
    TitleRule,
)
from app.infrastructure.llm.structured_prompt_builder import (
    build_structured_system_prompt,
    build_structured_user_prompt,
)


class TestStructuredGenerationModels:
    """结构化生成数据模型测试"""

    def test_generated_element_text(self):
        el = GeneratedElement(id="text_1", type="text", content="标题内容")
        assert el.id == "text_1"
        assert el.type == "text"
        assert el.content == "标题内容"
        assert el.headers is None
        assert el.rows is None

    def test_generated_element_table(self):
        el = GeneratedElement(
            id="table_1",
            type="table",
            headers=["列1", "列2"],
            rows=[["值1", "值2"]],
        )
        assert el.headers == ["列1", "列2"]
        assert el.rows == [["值1", "值2"]]
        assert el.content is None

    def test_structured_page_result_should_generate(self):
        result = StructuredPageResult(
            page_no=1,
            should_generate=True,
            elements=[GeneratedElement(id="text_1", type="text", content="标题")],
        )
        assert result.page_no == 1
        assert result.should_generate is True
        assert len(result.elements) == 1
        assert result.skip_reason == ""

    def test_structured_page_result_skip(self):
        result = StructuredPageResult(
            page_no=2,
            should_generate=False,
            skip_reason="无相关内容",
        )
        assert result.should_generate is False
        assert result.skip_reason == "无相关内容"
        assert result.elements == []

    def test_bounding_box_defaults(self):
        bbox = BoundingBox()
        assert bbox.x == 0
        assert bbox.y == 0
        assert bbox.w == 0
        assert bbox.h == 0

    def test_table_schema_defaults(self):
        schema = TableSchema(rows=3, cols=2)
        assert schema.rows == 3
        assert schema.cols == 2
        assert schema.default_cells is None
        assert schema.max_rows is None

    def test_template_rules_serialization(self):
        rules = TemplateRules(
            template=TemplateMeta(
                file_name="test.pptx",
                slide_count=2,
                slide_size=SlideSize(cx=9144000, cy=6858000),
            ),
            pages=[
                PageRule(
                    page_no=1,
                    page_name="封面",
                    page_purpose="cover",
                    supports_mermaid=False,
                    title=TitleRule(text="标题"),
                    elements=[],
                ),
            ],
        )
        dumped = rules.model_dump(mode="json")
        assert dumped["template"]["file_name"] == "test.pptx"
        assert dumped["template"]["slide_count"] == 2
        assert len(dumped["pages"]) == 1
        assert dumped["pages"][0]["page_name"] == "封面"

    def test_element_rule_with_table_schema(self):
        rule = ElementRule(
            id="table_1",
            shape_id=5,
            type="table",
            role="table",
            page_no=1,
            bbox=BoundingBox(x=100, y=200, w=300, h=400),
            z_order=1,
            editable=True,
            table_schema=TableSchema(rows=3, cols=2),
        )
        assert rule.table_schema.rows == 3
        assert rule.bbox.x == 100
        assert rule.editable is True


class TestStructuredPromptBuilder:
    """结构化生成 Prompt 构建器测试"""

    def test_system_prompt_contains_json(self):
        prompt = build_structured_system_prompt()
        assert "JSON" in prompt
        assert "text" in prompt
        assert "table" in prompt

    def test_user_prompt_contains_requirement(self):
        page_rule = {
            "page_no": 1,
            "page_name": "封面",
            "page_purpose": "cover",
            "title": {"text": "标题"},
            "elements": [
                {
                    "id": "text_1",
                    "type": "text",
                    "role": "title",
                    "bbox": {"x": 0, "y": 0, "w": 100, "h": 50},
                    "content_requirement": "生成标题",
                    "fill_strategy": "replace_text",
                    "is_instructional": False,
                }
            ],
        }
        prompt = build_structured_user_prompt("这是一个测试需求", page_rule)
        assert "这是一个测试需求" in prompt
        assert "text_1" in prompt
        assert "JSON" in prompt

    def test_user_prompt_includes_table_schema(self):
        page_rule = {
            "page_no": 2,
            "page_name": "表格页",
            "page_purpose": "table",
            "title": {"text": ""},
            "elements": [
                {
                    "id": "table_1",
                    "type": "table",
                    "role": "table",
                    "bbox": {"x": 0, "y": 0, "w": 200, "h": 100},
                    "content_requirement": "填写表格",
                    "fill_strategy": "fill_table",
                    "table_schema": {"rows": 3, "cols": 2},
                    "is_instructional": False,
                }
            ],
        }
        prompt = build_structured_user_prompt("表格需求", page_rule)
        assert "table_1" in prompt
        assert "table_schema" in prompt


class TestStructuredResultParsing:
    """LLM 返回结果解析测试"""

    def test_parse_valid_json(self):
        from app.infrastructure.llm.openai_like_client import OpenAILikePageGenerationClient

        content = json.dumps({
            "page_no": 1,
            "should_generate": True,
            "skip_reason": "",
            "elements": [
                {"id": "text_1", "type": "text", "content": "测试标题"},
                {"id": "table_1", "type": "table", "headers": ["A", "B"], "rows": [["1", "2"]]},
            ],
        })
        result = OpenAILikePageGenerationClient._parse_structured_result(content, 1)
        assert result.page_no == 1
        assert result.should_generate is True
        assert len(result.elements) == 2
        assert result.elements[0].content == "测试标题"
        assert result.elements[1].headers == ["A", "B"]

    def test_parse_json_with_code_fence(self):
        from app.infrastructure.llm.openai_like_client import OpenAILikePageGenerationClient

        content = '```json\n{"page_no": 2, "should_generate": false, "skip_reason": "无内容", "elements": []}\n```'
        result = OpenAILikePageGenerationClient._parse_structured_result(content, 2)
        assert result.page_no == 2
        assert result.should_generate is False
        assert result.skip_reason == "无内容"

    def test_parse_json_array(self):
        from app.infrastructure.llm.openai_like_client import OpenAILikePageGenerationClient

        content = json.dumps([{
            "page_no": 3,
            "should_generate": True,
            "elements": [{"id": "text_1", "type": "text", "content": "内容"}],
        }])
        result = OpenAILikePageGenerationClient._parse_structured_result(content, 3)
        assert result.page_no == 3
        assert len(result.elements) == 1

    def test_parse_missing_page_no_uses_default(self):
        from app.infrastructure.llm.openai_like_client import OpenAILikePageGenerationClient

        content = json.dumps({"should_generate": True, "elements": []})
        result = OpenAILikePageGenerationClient._parse_structured_result(content, 5)
        assert result.page_no == 5
