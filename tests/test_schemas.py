"""请求/响应模型校验测试"""
from __future__ import annotations

import pytest

from app.schemas.common import ApiResponse, SchemaModel
from app.schemas.task import (
    CreateGenerationTaskRequest,
    GenerationOptionsSchema,
    GenerationTaskSummarySchema,
)
from app.schemas.template import (
    TemplateSummarySchema,
    TemplateImportResponseSchema,
)


class TestApiResponse:
    def test_default_values(self):
        r = ApiResponse()
        assert r.code == 0
        assert r.message == "ok"
        assert r.data is None

    def test_with_data(self):
        r = ApiResponse(data={"key": "value"})
        assert r.data == {"key": "value"}

    def test_extra_fields_ignored(self):
        r = ApiResponse(code=200, message="success", data="ok", extra_field="ignored")
        assert not hasattr(r, "extra_field")


class TestCreateGenerationTaskRequest:
    def test_minimal_valid(self):
        req = CreateGenerationTaskRequest(requirement_text="测试需求")
        assert req.requirement_text == "测试需求"
        assert req.template_id is None
        assert req.options is None

    def test_with_template_id(self):
        req = CreateGenerationTaskRequest(
            requirement_text="测试",
            template_id="tpl_123",
        )
        assert req.template_id == "tpl_123"

    def test_with_options(self):
        req = CreateGenerationTaskRequest(
            requirement_text="测试",
            options=GenerationOptionsSchema(
                output_filename="demo.pptx",
                max_page_concurrency=4,
                keep_artifacts=True,
            ),
        )
        assert req.options.output_filename == "demo.pptx"
        assert req.options.max_page_concurrency == 4
        assert req.options.keep_artifacts is True

    def test_requirement_text_required(self):
        with pytest.raises(Exception):
            CreateGenerationTaskRequest()

    def test_task_id_optional(self):
        req = CreateGenerationTaskRequest(
            requirement_text="测试",
            task_id="custom_task_id_001",
        )
        assert req.task_id == "custom_task_id_001"

    def test_curl_format_payload(self, curl_data):
        """验证 curl.txt 中的请求格式能通过校验"""
        req = CreateGenerationTaskRequest.model_validate(curl_data)
        assert req.requirement_text is not None
        assert len(req.requirement_text) > 100
        assert req.template_id is None
        assert req.options is not None
        assert req.options.output_filename == "demo.pptx"


class TestGenerationOptionsSchema:
    def test_all_optional(self):
        opts = GenerationOptionsSchema()
        assert opts.max_page_concurrency is None
        assert opts.keep_artifacts is None
        assert opts.output_filename is None
        assert opts.model is None
        assert opts.enable_thinking is False

    def test_partial(self):
        opts = GenerationOptionsSchema(output_filename="result.pptx")
        assert opts.output_filename == "result.pptx"

    def test_model_and_enable_thinking(self):
        opts = GenerationOptionsSchema(
            model="qwen3.6-27b",
            enable_thinking=True,
        )
        assert opts.model == "qwen3.6-27b"
        assert opts.enable_thinking is True

    def test_enable_thinking_default_false(self):
        opts = GenerationOptionsSchema()
        assert opts.enable_thinking is False

    def test_model_default_none(self):
        opts = GenerationOptionsSchema()
        assert opts.model is None


class TestTemplateSchemas:
    def test_template_summary_required_fields(self):
        data = TemplateSummarySchema(
            template_id="tpl_001",
            template_name="测试模板",
            source_type="custom",
            status="ready",
            is_builtin=False,
        )
        assert data.template_id == "tpl_001"
        assert data.is_builtin is False

    def test_template_import_response(self):
        data = TemplateImportResponseSchema(
            template_id="tpl_002",
            template_name="导入模板",
            slide_count=5,
            status="ready",
        )
        assert data.slide_count == 5
