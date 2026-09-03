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


class TestDiagramPrompt:
    """单图 SVG prompt 测试"""

    def test_diagram_system_prompt_contains_rules(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_diagram_system_prompt()
        assert "产品/系统用矩形" in prompt
        assert "实线箭头" in prompt
        assert "虚线箭头" in prompt
        assert "viewBox" in prompt
        assert "不输出整页 PPT 模板" in prompt

    def test_diagram_system_prompt_contains_style_colors(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_diagram_system_prompt()
        assert "浅红色" in prompt
        assert "联机" in prompt
        assert "批量" in prompt

    def test_diagram_user_prompt_contains_params(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_diagram_user_prompt(
            requirement_text="系统包含 A、B 两个模块。",
            page_no=2,
            page_name="slide_2",
            page_title="产品连接关系图",
            custom_requirements="画架构图",
        )
        assert "系统包含 A、B 两个模块" in prompt
        assert "产品连接关系图" in prompt
        assert "画架构图" in prompt
        assert "只返回完整 SVG" in prompt


class TestPageGenerationRuleMatcher:
    """全局页面生成规范匹配器测试"""

    def test_match_cover_and_format(self):
        from app.infrastructure.llm.rule_matcher import PageGenerationRuleMatcher

        rules = [
            {
                "id": "global_page_rule_001",
                "enabled": True,
                "template_scope": ["*"],
                "title_match": {
                    "mode": "any_contains",
                    "keywords": ["封面"],
                    "normalize_whitespace": True,
                    "ignore_suffixes": ["（续）", "(续)"],
                },
                "apply_to": ["planning", "body"],
                "instruction": "封面必须生成。",
                "priority": 100,
            },
            {
                "id": "global_page_rule_002",
                "enabled": True,
                "template_scope": ["*"],
                "title_match": {
                    "mode": "any_contains",
                    "keywords": ["需求背景"],
                    "normalize_whitespace": True,
                    "ignore_suffixes": ["（续）", "(续)"],
                },
                "apply_to": ["body"],
                "instruction": "从需求背景中提炼。",
                "priority": 70,
            },
        ]
        matcher = PageGenerationRuleMatcher(rules)
        matched = matcher.match("项目封面", "planning")
        assert len(matched) == 1
        assert matched[0]["id"] == "global_page_rule_001"

    def test_match_respects_apply_to(self):
        from app.infrastructure.llm.rule_matcher import PageGenerationRuleMatcher

        rules = [
            {
                "id": "rule_001",
                "enabled": True,
                "title_match": {"mode": "any_contains", "keywords": ["需求背景"], "normalize_whitespace": True, "ignore_suffixes": []},
                "apply_to": ["body"],
                "instruction": "body only",
                "priority": 70,
            }
        ]
        matcher = PageGenerationRuleMatcher(rules)
        assert len(matcher.match("需求背景", "planning")) == 0
        assert len(matcher.match("需求背景", "body")) == 1

    def test_format_rules_for_prompt(self):
        from app.infrastructure.llm.rule_matcher import PageGenerationRuleMatcher

        matcher = PageGenerationRuleMatcher([
            {"id": "rule_001", "enabled": True, "instruction": "不要编造", "priority": 1000, "apply_to": ["body"], "title_match": {"keywords": [], "ignore_suffixes": []}}
        ])
        text = matcher.format_rules_for_prompt(matcher.match("任意", "body"))
        assert "rule_001" in text
        assert "不要编造" in text


class TestPageRulesInPrompt:
    """验证全局页面生成规范正确注入 Prompt"""

    def test_plan_system_prompt_contains_page_rules(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_plan_system_prompt(page_generation_rules_text="封面必须生成。")
        assert "全局页面生成规范" in prompt
        assert "封面必须生成" in prompt

    def test_generate_user_prompt_contains_page_rules(self):
        builder = PageAnalysisPromptBuilder()
        prompt = builder.build_generate_user_prompt(
            requirement_text="需求",
            page_no=2,
            page_name="需求背景",
            page_type="content",
            page_title="背景",
            svg_content="<svg/>",
            page_generation_rules_text="从需求背景中提炼。",
        )
        assert "本章节必须遵守的生成规范" in prompt
        assert "从需求背景中提炼" in prompt
