"""结构化填充编排服务。

封装模板解析 + 结构化 LLM 生成 + 结果收集的完整流程。
在编排服务中，非 SVG 页面（cover/toc/content/end）通过此服务处理。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.infrastructure.llm.base import BasePageGenerationClient
from app.infrastructure.ppt_master.template_rule_parser import TemplateRuleParser
from app.schemas.structured_generation import StructuredPageResult


logger = logging.getLogger(__name__)


class PptxBuilderService:
    """结构化填充编排服务。"""

    def __init__(
        self,
        generation_client: BasePageGenerationClient | None = None,
    ) -> None:
        self.generation_client = generation_client

    def parse_template_rules(
        self,
        template_pptx_path: Path,
        output_path: Path | None = None,
    ) -> dict:
        """解析模板 PPTX，返回模板规则 JSON dict。

        Args:
            template_pptx_path: 模板 PPTX 文件路径
            output_path: 可选，保存规则 JSON 的路径
        Returns:
            模板规则 dict（TemplateRules.model_dump() 的结果）
        """
        parser = TemplateRuleParser(template_pptx_path)
        rules = parser.parse()
        rules_dict = rules.model_dump(mode="json", exclude_none=True)
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(rules_dict, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return rules_dict

    def generate_page_content(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        page_name: str,
        page_rule: dict,
        model: str | None = None,
        enable_thinking: bool = False,
    ) -> StructuredPageResult:
        """调用 LLM 生成单页结构化内容。

        Args:
            api_key: LLM API Key
            requirement_text: 需求全文
            page_no: 页码
            page_name: 页面名称
            page_rule: 该页的模板规则 dict
            model: 可选模型名称
            enable_thinking: 是否启用思考模式
        Returns:
            StructuredPageResult
        """
        if self.generation_client is None:
            return StructuredPageResult(
                page_no=page_no,
                should_generate=False,
                skip_reason="生成客户端未配置",
                elements=[],
            )
        return self.generation_client.generate_page_content(
            api_key=api_key,
            requirement_text=requirement_text,
            page_no=page_no,
            page_name=page_name,
            page_rule=page_rule,
            model=model,
            enable_thinking=enable_thinking,
        )

    def save_page_result(
        self,
        workspace,
        page_no: int,
        result: StructuredPageResult,
    ) -> Path:
        """保存结构化生成结果到工作区。"""
        output_path = workspace.structured_results_dir / f"page_{page_no:02d}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path

    def load_page_result(self, file_path: Path) -> StructuredPageResult:
        """从 JSON 文件加载结构化生成结果。"""
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return StructuredPageResult.model_validate(data)
