"""LLM 客户端测试：重试逻辑、参数透传、SVG 提取、回退"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings
from app.infrastructure.llm.openai_like_client import OpenAILikePageGenerationClient
from app.infrastructure.llm.prompt_builder import PageAnalysisPromptBuilder


def make_settings(tmp_path) -> Settings:
    return Settings(
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
        llm_base_url="https://test.api.host",
        llm_model="test-model",
        llm_timeout_seconds=10,
    )


def make_client(tmp_path) -> OpenAILikePageGenerationClient:
    settings = make_settings(tmp_path)
    builder = PageAnalysisPromptBuilder()
    return OpenAILikePageGenerationClient(settings, builder)


class TestEnabled:
    def test_enabled_when_url_and_model_set(self, tmp_path):
        client = make_client(tmp_path)
        assert client.enabled is True

    def test_disabled_when_no_url(self, tmp_path):
        settings = make_settings(tmp_path)
        settings.llm_base_url = ""
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())
        assert client.enabled is False

    def test_disabled_when_no_model(self, tmp_path):
        settings = make_settings(tmp_path)
        settings.llm_model = ""
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())
        assert client.enabled is False


class TestApiUrl:
    def test_appends_v1(self, tmp_path):
        client = make_client(tmp_path)
        assert client._api_url == "https://test.api.host/v1/chat/completions"

    def test_no_double_v1(self, tmp_path):
        settings = make_settings(tmp_path)
        settings.llm_base_url = "https://test.api.host/v1"
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())
        assert client._api_url == "https://test.api.host/v1/chat/completions"


class TestPlanFallback:
    def test_disabled_returns_heuristic(self, tmp_path):
        """LLM 未配置时回退启发式"""
        settings = make_settings(tmp_path)
        settings.llm_base_url = ""
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())
        result = client.plan_single_page("key", "需求", 1, "封面", "<svg/>", 3)
        assert result.decision_source == "heuristic"
        assert result.should_generate is True
        assert result.page_type == "cover"

    def test_fallback_last_page_is_end(self, tmp_path):
        settings = make_settings(tmp_path)
        settings.llm_base_url = ""
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())
        result = client.plan_single_page("key", "需求", 5, "尾页", "<svg/>", 5)
        assert result.page_type == "end"

    def test_fallback_toc_detection(self, tmp_path):
        settings = make_settings(tmp_path)
        settings.llm_base_url = ""
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())
        result = client.plan_single_page("key", "需求", 2, "目录页", "<svg/>", 5)
        assert result.page_type == "toc"

    def test_fallback_diagram_detection(self, tmp_path):
        settings = make_settings(tmp_path)
        settings.llm_base_url = ""
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())
        result = client.plan_single_page("key", "需求", 3, "系统架构图", "<svg/>", 5)
        assert result.page_type == "diagram"

    def test_fallback_content_default(self, tmp_path):
        settings = make_settings(tmp_path)
        settings.llm_base_url = ""
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())
        result = client.plan_single_page("key", "需求", 3, "方案介绍", "<svg/>", 5)
        assert result.page_type == "content"

    def test_empty_api_key_returns_fallback(self, tmp_path):
        """API Key 为空时回退"""
        client = make_client(tmp_path)
        result = client.plan_single_page("", "需求", 1, "封面", "<svg/>", 3)
        assert result.decision_source == "heuristic"


class TestPlanRetry:
    def test_retry_3_times_then_fallback(self, tmp_path):
        """LLM 调用失败 3 次后回退启发式"""
        client = make_client(tmp_path)
        with patch.object(client, "_call_llm", side_effect=Exception("network error")):
            result = client.plan_single_page("key", "需求", 1, "封面", "<svg/>", 3)
        assert result.decision_source == "heuristic"
        assert result.should_generate is True

    def test_retry_succeeds_on_second_attempt(self, tmp_path):
        """第一次失败、第二次成功"""
        client = make_client(tmp_path)
        good_response = '{"should_generate": true, "skip_reason": "", "page_type": "content", "page_title": "测试"}'
        with patch.object(client, "_call_llm", side_effect=[Exception("fail"), good_response]):
            result = client.plan_single_page("key", "需求", 2, "内容", "<svg/>", 5)
        assert result.decision_source == "llm"
        assert result.page_title == "测试"


class TestGenerateRetry:
    def test_retry_3_times_returns_failed(self, tmp_path):
        """生成失败 3 次后返回 decision_source=failed"""
        client = make_client(tmp_path)
        with patch.object(client, "_call_llm", side_effect=Exception("network error")):
            result = client.generate_page_svg("key", "需求", 2, "内容", "content", "标题", "<svg/>")
        assert result.decision_source == "failed"
        assert result.generated_svg is None

    def test_generate_succeeds(self, tmp_path):
        """生成成功返回 SVG"""
        client = make_client(tmp_path)
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540"><text>hello</text></svg>'
        with patch.object(client, "_call_llm", return_value=svg_content):
            result = client.generate_page_svg("key", "需求", 2, "内容", "content", "标题", "<svg/>")
        assert result.decision_source == "llm"
        assert result.generated_svg is not None
        assert "<svg" in result.generated_svg

    def test_generate_no_svg_in_response_returns_failed(self, tmp_path):
        """LLM 返回内容中无 SVG，重试后返回 failed"""
        client = make_client(tmp_path)
        with patch.object(client, "_call_llm", return_value="这不是 SVG 内容"):
            result = client.generate_page_svg("key", "需求", 2, "内容", "content", "标题", "<svg/>")
        assert result.decision_source == "failed"

    def test_disabled_returns_heuristic(self, tmp_path):
        """LLM 未配置时生成回退 heuristic"""
        settings = make_settings(tmp_path)
        settings.llm_base_url = ""
        client = OpenAILikePageGenerationClient(settings, PageAnalysisPromptBuilder())
        result = client.generate_page_svg("key", "需求", 2, "内容", "content", "标题", "<svg/>")
        assert result.decision_source == "heuristic"
        assert result.generated_svg is None


class TestExtractSvg:
    def test_plain_svg(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>test</text></svg>'
        result = OpenAILikePageGenerationClient._extract_svg(svg)
        assert result is not None
        assert "<svg" in result

    def test_svg_in_markdown_codeblock(self):
        content = '```svg\n<svg xmlns="http://www.w3.org/2000/svg"><rect/>\n</svg>\n```'
        result = OpenAILikePageGenerationClient._extract_svg(content)
        assert result is not None
        assert "<svg" in result
        assert "```" not in result

    def test_svg_embedded_in_text(self):
        content = '这是生成结果：\n<svg xmlns="http://www.w3.org/2000/svg"><text>hi</text></svg>\n结束'
        result = OpenAILikePageGenerationClient._extract_svg(content)
        assert result is not None
        assert result.startswith("<svg")

    def test_no_svg_returns_none(self):
        result = OpenAILikePageGenerationClient._extract_svg("没有 SVG 内容")
        assert result is None

    def test_xml_declaration(self):
        content = '<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>'
        result = OpenAILikePageGenerationClient._extract_svg(content)
        assert result is not None


class TestParsePlanResponse:
    def test_valid_json(self):
        content = '{"should_generate": true, "skip_reason": "", "page_type": "content", "page_title": "测试"}'
        result = OpenAILikePageGenerationClient._parse_single_plan_response(content, 1, "页1")
        assert result.should_generate is True
        assert result.page_type == "content"
        assert result.page_title == "测试"
        assert result.decision_source == "llm"

    def test_json_in_codeblock(self):
        content = '```json\n{"should_generate": false, "skip_reason": "无关页", "page_type": "content", "page_title": ""}\n```'
        result = OpenAILikePageGenerationClient._parse_single_plan_response(content, 2, "页2")
        assert result.should_generate is False
        assert result.skip_reason == "无关页"

    def test_json_array_takes_first(self):
        content = '[{"should_generate": true, "skip_reason": "", "page_type": "cover", "page_title": "封面"}]'
        result = OpenAILikePageGenerationClient._parse_single_plan_response(content, 1, "封面")
        assert result.should_generate is True
        assert result.page_type == "cover"


class TestCallLlmParams:
    def test_model_param_passed_to_payload(self, tmp_path):
        """_call_llm 使用传入的 model 参数"""
        client = make_client(tmp_path)
        captured_payload = {}

        def fake_stream(payload, headers, timeout):
            captured_payload.update(payload)
            return "test response"

        with patch.object(client, "_call_stream", side_effect=fake_stream):
            client._call_llm("key", "sys", "user", stream=True, model="custom-model", enable_thinking=True)

        assert captured_payload["model"] == "custom-model"
        assert captured_payload["enable_thinking"] is True

    def test_model_falls_back_to_settings(self, tmp_path):
        """不传 model 时使用 settings.llm_model"""
        client = make_client(tmp_path)
        captured_payload = {}

        def fake_stream(payload, headers, timeout):
            captured_payload.update(payload)
            return "test response"

        with patch.object(client, "_call_stream", side_effect=fake_stream):
            client._call_llm("key", "sys", "user", stream=True)

        assert captured_payload["model"] == "test-model"
        assert captured_payload["enable_thinking"] is False
