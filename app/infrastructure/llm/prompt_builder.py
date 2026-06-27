from __future__ import annotations


class PageAnalysisPromptBuilder:
    def build_system_prompt(self) -> str:
        return (
            "你是 PPT 页面规划助手。你的任务是根据需求文本和模板页 SVG 内容，"
            "为每一页生成内容规划，并给出对模板中已有文字的替换建议。\n\n"
            "输出要求：\n"
            "1. 只输出 JSON 对象，不要 markdown，不要代码块。\n"
            "2. 必须包含以下字段：\n"
            "   - page_no: 页码（整数）\n"
            "   - page_name: 页面名称\n"
            "   - should_generate: 该页是否需要生成内容（布尔值）\n"
            "   - skip_reason: 跳过原因（如不跳过则为空字符串）\n"
            "   - page_title: 该页标题（根据需求提炼，不要直接用模板页名）\n"
            "   - page_summary: 该页内容摘要（1-2句话概括该页要展示的核心内容）\n"
            "   - bullet_points: 要点列表（字符串数组，最多5条）\n"
            "   - diagram_kind: 图形类型（如 architecture/sequence/flowchart，无则为 null）\n"
            "   - text_replacements: 模板文字替换列表，数组中每项包含 original_text 和 new_text\n"
            "3. text_replacements 的填写规则：\n"
            "   - 仔细阅读 SVG 中的 <text> 和 <tspan> 元素内容，找出模板中的占位文字、示例文字或需要更新的文字\n"
            "   - 常见占位文字如 \"XX\"、\"20XX\"、\"项目技术方案汇报\"、\"文档编号\" 等\n"
            "   - 根据需求文本，将这些占位文字替换为实际内容\n"
            "   - original_text 必须与 SVG 中出现的文字完全一致（包括空格和标点）\n"
            "   - 如果某个文字不需要替换，不要将它放入 text_replacements\n"
            "   - 如果模板中没有需要替换的文字，text_replacements 为空数组 []\n"
            "4. 如果该页没有足够信息可生成，should_generate=false 并给出 skip_reason。\n"
            "5. bullet_points 最多 5 条，每条不超过 60 个字。"
        )

    def build_user_prompt(
        self,
        requirement_text: str,
        page_no: int,
        page_name: str,
        svg_excerpt: str,
    ) -> str:
        return (
            f"需求文本：\n{requirement_text.strip()}\n\n"
            f"当前页页码：{page_no}\n"
            f"当前页名称：{page_name}\n\n"
            f"当前页模板 SVG 内容（请仔细阅读其中的文字元素，理解版式与占位符）：\n{svg_excerpt.strip()}\n\n"
            "请分析这一页应该展示什么内容，并给出对模板中已有文字的替换建议。\n"
            "只返回 JSON 对象。"
        )
