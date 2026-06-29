from __future__ import annotations


class PageAnalysisPromptBuilder:
    def build_plan_system_prompt(self) -> str:
        return (
            "你是 PPT 页面规划助手。你的任务是根据需求文本和单页模板 SVG 内容，"
            "判断该页是否需要生成内容，并给出页面类型和标题。\n\n"
            "输出要求：\n"
            "1. 只输出一个 JSON 对象，不要 markdown，不要代码块。\n"
            "2. JSON 对象包含以下字段：\n"
            "   - should_generate: 该页是否需要生成内容（布尔值）\n"
            "   - skip_reason: 跳过原因（如不跳过则为空字符串）\n"
            "   - page_type: 页面类型，取值为 cover/toc/content/diagram/end 之一\n"
            "     * cover: 封面页（项目名称、文档编号、日期等）\n"
            "     * toc: 目录页\n"
            "     * content: 普通内容页（文字为主）\n"
            "     * diagram: 图形页（架构图、流程图、时序图等需要画图的页面）\n"
            "     * end: 结尾页（感谢页等）\n"
            "   - page_title: 该页标题（根据需求和模板内容提炼）\n"
            "3. 判断 should_generate 的规则：\n"
            "   - 封面页(cover)、尾页(end)、目录页(toc)始终设为 true，因为这些页面必须存在\n"
            "   - 仔细阅读模板 SVG 中的文字内容，如果该页有占位文字、填写说明、示例内容，"
            "且需求文本中有对应内容可填，设为 true\n"
            "   - 如果该页模板内容与需求文本完全无关（如纯装饰页、空白页、无对应内容），设为 false，"
            "并在 skip_reason 中说明原因\n"
            "4. 判断 page_type 的规则：\n"
            "   - 根据模板页 SVG 中的文字和结构判断页面类型\n"
            "   - 模板中包含 \"架构图\"、\"流程图\"、\"时序图\" 等关键词的页面应为 diagram\n"
            "   - 第一页通常为 cover，最后一页通常为 end\n"
            "   - 包含目录结构的页面为 toc\n"
            "5. 只返回 JSON 对象，不要任何其他文字。"
        )

    def build_plan_user_prompt(
        self,
        requirement_text: str,
        page_no: int,
        page_name: str,
        svg_content: str,
    ) -> str:
        return (
            f"需求文本：\n{requirement_text.strip()}\n\n"
            f"当前是第 {page_no} 页，页面名称：{page_name}\n\n"
            f"该页模板 SVG 内容：\n{svg_content.strip()}\n\n"
            "请根据需求文本和该页模板内容，判断这一页是否需要生成内容，并给出页面类型和标题。只返回 JSON 对象。"
        )

    def build_generate_system_prompt(self, page_type: str) -> str:
        common = (
            "你是一个 PPT 页面 SVG 生成助手。你的任务是：根据需求文本和模板页的版面结构，"
            "生成一个全新的完整 SVG 文件。\n\n"
            "核心原则：\n"
            "1. 直接输出完整 SVG 代码，不要输出任何解释、markdown 或代码块标记。\n"
            "2. 参考模板页的版面结构（矩形位置、颜色方案、字体大小），但不要保留模板中的占位文字和填写说明。\n"
            "3. 模板中的【填写说明】、示例文字、占位符等全部删除，替换为根据需求生成的实际内容。\n"
            "4. 保持 SVG 的 xmlns 命名空间、viewBox、width、height 等属性不变。\n"
            "5. 输出的 SVG 必须是完整的、可独立解析的 SVG 文件。\n"
            "6. 排版规则（非常重要）：\n"
            "   - 参考模板中各文本框的 y 坐标来放置内容，不要自行创造过大的间距\n"
            "   - 章节标题之间、段落之间保持紧凑，不要留下大段空白（不超过50像素的间距）\n"
            "   - 同一文本框内的多行文字使用 tspan 的 dy 属性换行，行间距设为24-28像素\n"
            "   - 不要让不同文本框的文字在 y 坐标上重叠\n"
            "   - 所有内容必须在 viewBox 范围内（y 坐标不超过 720）\n"
            "   - 如果内容较多，适当缩小行间距而非让文字超出页面底部\n"
        )

        if page_type == "cover":
            return common + (
                "\n封面页特殊要求：\n"
                "- 根据需求文本填入项目名称、副标题、文档编号、日期、部门等信息\n"
                "- 保持模板的封面装饰元素（色块、线条等）不变\n"
                "- 标题文字使用模板中的字体大小和颜色\n"
            )
        elif page_type == "toc":
            return common + (
                "\n目录页特殊要求：\n"
                "- 根据需求文本的章节结构生成目录条目\n"
                "- 每个目录条目包含章节编号和标题\n"
                "- 保持模板中目录项的排版格式\n"
            )
        elif page_type == "diagram":
            return common + (
                "\n图形页特殊要求：\n"
                "- 在模板中图形占位区域的位置，用 SVG 基本图形元素（rect、line、path、text）绘制架构图或流程图\n"
                "- 用矩形表示系统/模块，用线条和箭头表示连接关系\n"
                "- 每个矩形内填写系统名称，线条旁可标注接口类型\n"
                "- 新建系统用特殊颜色标识，现有系统用灰色或无填充\n"
                "- 联机接口用实线，批量接口用虚线\n"
                "- 图形元素必须使用 SVG 基本标签（rect、line、path、text），不要使用 image 标签\n"
                "- 图形要适配模板中预留的图形区域大小和位置\n"
            )
        elif page_type == "end":
            return common + (
                "\n结尾页特殊要求：\n"
                "- 填入感谢语、联系方式等\n"
                "- 保持模板的装饰元素不变\n"
            )
        else:
            return common + (
                "\n内容页特殊要求：\n"
                "- 根据需求文本中对应章节的内容生成标题和正文要点\n"
                "- 标题使用模板中的标题样式（字体大小、颜色、粗细）\n"
                "- 正文使用模板中的正文字体大小和颜色\n"
                "- 不要保留模板中的填写说明文字，全部替换为实际内容\n"
                "- 要点内容简明扼要，每条不超过一行\n"
            )

    def build_generate_user_prompt(
        self,
        requirement_text: str,
        page_no: int,
        page_name: str,
        page_type: str,
        page_title: str,
        svg_content: str,
    ) -> str:
        return (
            f"需求文本：\n{requirement_text.strip()}\n\n"
            f"当前是第 {page_no} 页，页面名称：{page_name}\n"
            f"页面类型：{page_type}\n"
            f"页面标题：{page_title}\n\n"
            f"模板页 SVG 内容（参考其版面结构和样式，但不要保留占位文字）：\n{svg_content.strip()}\n\n"
            "请根据需求文本的内容，参考模板的版面结构，生成一个全新的完整 SVG。"
        )
