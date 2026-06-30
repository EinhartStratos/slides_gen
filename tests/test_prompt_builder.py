"""Prompt 构建器测试"""
from __future__ import annotations

from app.infrastructure.llm.prompt_builder import PageAnalysisPromptBuilder


class TestPlanSystemPrompt:
    def test_contains_json_instruction(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_plan_system_prompt()
        assert "JSON" in prompt
        assert "should_generate" in prompt
        assert "page_type" in prompt

    def test_contains_page_types(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_plan_system_prompt()
        assert "cover" in prompt
        assert "toc" in prompt
        assert "content" in prompt
        assert "diagram" in prompt
        assert "end" in prompt

    def test_cover_always_generate(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_plan_system_prompt()
        assert "始终设为 true" in prompt


class TestPlanUserPrompt:
    def test_contains_requirement_and_svg(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_plan_user_prompt(
            requirement_text="测试需求",
            page_no=3,
            page_name="架构图",
            svg_content="<svg>test</svg>",
        )
        assert "测试需求" in prompt
        assert "3" in prompt
        assert "架构图" in prompt
        assert "<svg>test</svg>" in prompt


class TestGenerateSystemPrompt:
    def test_common_rules_present(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_generate_system_prompt("content")
        assert "完整 SVG" in prompt
        assert "排版规则" in prompt
        assert "viewBox" in prompt

    def test_textbox_rule_present(self):
        """验证防嵌套小文本框的 prompt 规则存在"""
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_generate_system_prompt("content")
        assert "tspan" in prompt
        assert "不要每行文字都单独创建" in prompt

    def test_cover_specific(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_generate_system_prompt("cover")
        assert "封面" in prompt
        assert "项目名称" in prompt

    def test_toc_specific(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_generate_system_prompt("toc")
        assert "目录" in prompt

    def test_diagram_specific(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_generate_system_prompt("diagram")
        assert "架构图" in prompt or "流程图" in prompt
        assert "rect" in prompt

    def test_end_specific(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_generate_system_prompt("end")
        assert "结尾" in prompt or "感谢" in prompt

    def test_content_specific(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_generate_system_prompt("content")
        assert "内容页" in prompt or "正文" in prompt


class TestGenerateUserPrompt:
    def test_contains_all_params(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_generate_user_prompt(
            requirement_text="需求全文",
            page_no=4,
            page_name="系统架构",
            page_type="diagram",
            page_title="总体架构",
            svg_content="<svg>template</svg>",
        )
        assert "需求全文" in prompt
        assert "4" in prompt
        assert "系统架构" in prompt
        assert "diagram" in prompt
        assert "总体架构" in prompt
        assert "<svg>template</svg>" in prompt
