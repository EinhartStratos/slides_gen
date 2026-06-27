from __future__ import annotations


class PageAnalysisPromptBuilder:
    def build_system_prompt(self) -> str:
        return (
            "你是 PPT 页面规划助手。"
            "请根据需求文本和模板页信息，输出严格 JSON。"
            "不要输出 markdown，不要输出代码块。"
            "字段必须包含：page_no,page_name,should_generate,skip_reason,page_title,page_summary,bullet_points,diagram_kind。"
            "bullet_points 必须是字符串数组，最多 5 条。"
            "如果该页没有足够信息，则 should_generate=false，并给出 skip_reason。"
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
            f"当前页 SVG 片段（用于理解版式与主题，不要求逐字符解析）：\n{svg_excerpt.strip()}\n\n"
            "请只返回 JSON 对象。"
        )
