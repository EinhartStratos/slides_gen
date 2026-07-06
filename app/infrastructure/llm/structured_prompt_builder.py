"""结构化内容生成的 Prompt 构建器。

从 pptx_gen/llm/prompts.py 移植，去掉 Mermaid 相关部分。
让 LLM 输出结构化 JSON（文本内容、表格数据），而非 SVG。
"""

from __future__ import annotations

import json


def build_structured_system_prompt(check_rules_text: str = "", custom_requirements: str = "") -> str:
    """构建结构化生成的 system prompt。

    Args:
        check_rules_text: 该页面匹配到的检查规则文本（已格式化）
        custom_requirements: 用户自定义的额外要求
    """
    prompt = (
        "你是一个严格输出 JSON 的 PPT 内容生成助手。"
        "你必须根据需求全文和单页模板规则判断该页是否应该生成。"
        "如果没有足够信息，必须返回 should_generate=false 和明确 skip_reason。"
        "只允许输出 text 和 table 两类元素。"
        "模板中的说明文字、填写说明、示例文案只可作为理解页面用途的参考，不能直接照抄到最终结果。"
        "正文内容应尽量压缩为可展示的要点，而不是把需求全文整段搬运进页面。"
        "如果某个元素只是模板说明占位，且当前需求不足以生成真实内容，可以省略该元素。"
        "禁止输出 Markdown 解释、禁止输出代码围栏、禁止输出额外说明。"
    )
    if check_rules_text:
        prompt += (
            "\n\n以下是该页面需要遵守的检查规则，生成内容时必须严格遵循：\n"
            f"{check_rules_text}"
        )
    if custom_requirements and custom_requirements.strip():
        prompt += (
            "\n\n以下是用户额外提出的自定义要求，生成内容时必须遵循：\n"
            f"{custom_requirements.strip()}"
        )
    return prompt


def _build_model_rule_view(page_rule: dict) -> dict:
    """构建给 LLM 看的精简页面规则。"""
    return {
        "page_no": page_rule["page_no"],
        "page_name": page_rule.get("page_name", ""),
        "page_purpose": page_rule.get("page_purpose", ""),
        "title": page_rule.get("title", {}),
        "elements": [
            {
                "id": element.get("id"),
                "type": element.get("type"),
                "role": element.get("role"),
                "bbox": element.get("bbox"),
                "content_requirement": element.get("content_requirement"),
                "fill_strategy": element.get("fill_strategy"),
                "table_schema": element.get("table_schema"),
                "is_instructional": element.get("is_instructional", False),
            }
            for element in page_rule.get("elements", [])
        ],
    }


def build_structured_user_prompt(requirement_text: str, page_rule: dict, custom_requirements: str = "") -> str:
    """构建结构化生成的 user prompt。

    Args:
        requirement_text: 需求全文
        page_rule: 该页的模板规则 dict
        custom_requirements: 用户自定义的额外要求
    """
    model_page_rule = _build_model_rule_view(page_rule)
    output_schema = {
        "page_no": page_rule["page_no"],
        "should_generate": True,
        "skip_reason": "",
        "elements": [
            {
                "id": "title_1",
                "type": "text",
                "content": "页面标题",
            },
            {
                "id": "table_2",
                "type": "table",
                "headers": ["列1", "列2"],
                "rows": [["值1", "值2"]],
            },
        ],
    }
    parts = [
        "请根据下面的需求全文和单页模板规则生成该页内容。\n\n"
        "要求：\n"
        "1. 先判断该页是否适合当前需求。\n"
        "2. 如果不适合，输出 should_generate=false，并写清 skip_reason。\n"
        "3. 文本框内容要简洁，优先提炼要点、分层列点，表格不要超过模板容量。\n"
        "4. 对 is_instructional=true 的元素，不要直接复述模板说明话术，应改写成真实业务内容；如果无法生成真实内容，可以省略该元素。\n"
        "5. 如果某个正文框的说明里提到「可分多页」或「分多页」，请优先按一级章节组织内容，避免单页堆满大段文字。\n"
        "6. 所有元素 id 必须严格复用模板规则里的 id。\n"
        "7. 不需要返回没有生成内容的元素。\n"
        "8. 只输出 JSON。\n"
        f"需求全文：\n{requirement_text}\n\n"
        f"单页模板规则：\n{json.dumps(model_page_rule, ensure_ascii=False, indent=2)}\n\n"
        f"输出 JSON 结构示例：\n{json.dumps(output_schema, ensure_ascii=False, indent=2)}",
    ]
    if custom_requirements and custom_requirements.strip():
        parts.append(f"\n\n用户自定义要求：\n{custom_requirements.strip()}")
    return "".join(parts)
