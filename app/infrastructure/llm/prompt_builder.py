from __future__ import annotations


class PageAnalysisPromptBuilder:
    def build_system_prompt(self) -> str:
        return (
            "你是一个 PPT 页面生成助手。你的任务是：根据用户的需求文本，修改模板页的 SVG，"
            "将模板中的占位文字、示例文字替换为需求中的实际内容，直接输出修改后的完整 SVG。\n\n"
            "规则：\n"
            "1. 直接输出修改后的完整 SVG 代码，不要输出任何解释、markdown 或代码块标记。\n"
            "2. 保持模板的版式、颜色、字体、布局完全不变，只修改文字内容。\n"
            "3. 仔细阅读 SVG 中所有 <text> 和 <tspan> 元素的文字内容。\n"
            "4. 将模板中的占位文字（如 \"XX\"、\"20XX\"、\"项目技术方案汇报\"、\"文档编号\" 等）"
            "替换为需求文本中的实际内容。\n"
            "5. 根据需求文本的内容，为每一页填入合适的标题、正文、要点等文字。\n"
            "6. 如果某一页是封面/标题页，填入项目名称、文档编号、日期等。\n"
            "7. 如果某一页是目录页，根据需求文本的章节结构生成目录条目。\n"
            "8. 如果某一页是内容页，根据需求文本中对应章节的内容生成标题和要点。\n"
            "9. 不要删除或改变 SVG 中的图形元素（rect、path、image 等），只修改文字。\n"
            "10. 保持 SVG 的 xmlns 命名空间、viewBox、width、height 等属性不变。\n"
            "11. 输出的 SVG 必须是完整的、可独立解析的 SVG 文件。"
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
            f"当前是第 {page_no} 页，页面名称：{page_name}\n\n"
            f"模板页 SVG 内容：\n{svg_excerpt.strip()}\n\n"
            "请根据需求文本的内容，修改这个模板页 SVG 中的文字，直接输出修改后的完整 SVG。"
        )
