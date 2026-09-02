from __future__ import annotations


# 产品/系统连接图通用绘制规范（从 v4 案例抽象而来）
DIAGRAM_DRAWING_RULES = """
通用画图规范（必须遵守）：

1. 元素表示
   - 产品/系统用矩形（<rect>）表示。
   - 需要改造的产品：填充浅红色 #ffcccc，边框 #d32f2f。
   - 仅配合测试的产品：无填充（透明/白色），边框 #999999。
   - 矩形内居中显示产品名称，字体 14-16px，颜色 #333333，粗细 normal。
   - 矩形尺寸 120x40 像素，同列/同行尽量对齐，间距不少于 30 像素。

2. 连接关系
   - 联机接口（http/IPS-D/实时调用）用实线箭头表示，颜色 #1976d2（蓝色）。
   - 批量接口（FTP/文件传输）用虚线箭头表示，stroke-dasharray="6,3"，颜色 #424242（深灰）。
   - 新增的系统关系：线条与箭头颜色用红色 #e53935，并在箭头旁标注“新增”。
   - 已有的系统关系：使用默认实线/虚线颜色，不额外标注。
   - 箭头旁标注接口形式（如 http、FTP、IPS-D），字体 10-12px，颜色 #555555。

3. 布局要求
   - 整体图形在 viewBox 中水平居中、底部偏下区域摆放（留出上半部分给模板标题/正文）。
   - 产品按属性从左到右分区域排列：
     渠道类 → 业务类 → 平台类 → 后线类
   - 同类产品在垂直方向上尽量对齐，区域之间留出 60-80 像素间隔。
   - 连线尽量减少交叉：优先使用直角折线（L 型），必要时用曲线或分段 path。

4. 输出要求
   - 只输出一个完整的 <svg> 元素，不要输出 markdown、代码块或整页 PPT 模板。
   - SVG 背景透明（不设置 fill 或 fill="none"）。
   - 建议 viewBox="0 0 900 320"，width="900"，height="320"，内容在 (50, 60) 到 (850, 280) 区域内。
   - 所有图形使用 SVG 基本标签：rect、line、path、text、tspan、marker（箭头）。
   - 不要使用 <image>、<foreignObject>、<style> 块或脚本。
"""



class PageAnalysisPromptBuilder:
    def build_plan_system_prompt(self, check_rules_text: str = "", page_generation_rules_text: str = "", custom_requirements: str = "") -> str:
        prompt = (
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
        if check_rules_text:
            prompt += (
                "\n\n以下是该页面需要遵守的检查规则，规划时请考虑这些规则的要求：\n"
                f"{check_rules_text}"
            )
        if page_generation_rules_text:
            prompt += (
                "\n\n【全局页面生成规范】命中本章节后必须遵守的正向生成要求（优先级高于检查规则）：\n"
                f"{page_generation_rules_text}"
            )
        if custom_requirements and custom_requirements.strip():
            prompt += (
                "\n\n以下是用户额外提出的自定义要求，规划时必须遵循：\n"
                f"{custom_requirements.strip()}"
            )
        return prompt

    def build_plan_user_prompt(
        self,
        requirement_text: str,
        page_no: int,
        page_name: str,
        svg_content: str,
        page_generation_rules_text: str = "",
        custom_requirements: str = "",
    ) -> str:
        parts = [
            f"需求文本：\n{requirement_text.strip()}\n\n",
            f"当前是第 {page_no} 页，页面名称：{page_name}\n\n",
            f"该页模板 SVG 内容：\n{svg_content.strip()}\n\n",
        ]
        if page_generation_rules_text:
            parts.append(f"本章节必须遵守的生成规范：\n{page_generation_rules_text}\n\n")
        if custom_requirements and custom_requirements.strip():
            parts.append(f"用户自定义要求：\n{custom_requirements.strip()}\n\n")
        parts.append("请根据需求文本、模板内容和上述生成规范，判断这一页是否需要生成内容，并给出页面类型和标题。只返回 JSON 对象。")
        return "".join(parts)

    def build_generate_system_prompt(self, page_type: str, check_rules_text: str = "", page_generation_rules_text: str = "", custom_requirements: str = "") -> str:
        common = (
            "你是一个 PPT 页面 SVG 生成助手。你的任务是：根据需求文本和模板页的版面结构，"
            "在模板 SVG 的基础上生成一个完整的 SVG 文件。\n\n"
            "核心原则（必须严格遵守）：\n"
            "1. 直接输出完整 SVG 代码，不要输出任何解释、markdown 或代码块标记。\n"
            "2. **严格保持模板页的版面结构**：必须复用模板中所有 <g>、<rect>、<text> 等元素的坐标（x、y）、"
            "尺寸（width、height）、颜色（fill、stroke）、字体大小（font-size）、字体粗细（font-weight）等属性。\n"
            "   - 不要自行创造新的布局位置，所有元素的坐标和尺寸必须与模板一致\n"
            "   - 不要改变模板的颜色方案，所有 fill、stroke 等颜色值必须与模板一致\n"
            "   - 不要改变模板的字体大小和样式，所有 font-size、font-weight、font-family 必须与模板一致\n"
            "   - 保持模板中的装饰元素（色块、线条、背景矩形等）原样不变\n"
            "3. 模板中的【填写说明】、示例文字、占位符等全部删除，替换为根据需求生成的实际内容。\n"
            "   - 只替换文字内容（tspan/text 的文本节点），不要改变容纳这些文字的元素的属性\n"
            "4. 保持 SVG 的 xmlns 命名空间、viewBox、width、height 等属性不变。\n"
            "5. 输出的 SVG 必须是完整的、可独立解析的 SVG 文件。\n"
            "6. 排版规则（非常重要）：\n"
            "   - 严格使用模板中各文本框的 y 坐标来放置内容，不要自行创造过大的间距\n"
            "   - 章节标题之间、段落之间保持紧凑，不要留下大段空白（不超过50像素的间距）\n"
            "   - 同一文本框内的多行文字使用 tspan 的 dy 属性换行，行间距设为24-28像素\n"
            "   - 不要让不同文本框的文字在 y 坐标上重叠\n"
            "   - 所有内容必须在 viewBox 范围内（y 坐标不超过 720）\n"
            "   - 如果内容较多，适当缩小行间距而非让文字超出页面底部\n"
            "   - 同一内容区域的多行文字应放在一个 <g> 组内用一个 <text> 元素配合多个 <tspan> 实现，"
            "不要每行文字都单独创建一个 <g> + <rect> + <text> 的小文本框\n"
            "   - 只有当内容确实需要区分标题和正文时，才使用不同的 <g> 组；"
            "如果全都是正文，则合并到一个文本框中\n"
        )

        if check_rules_text:
            common += (
                "\n\n以下是该页面需要遵守的检查规则，生成内容时必须严格遵循：\n"
                f"{check_rules_text}"
            )
        if page_generation_rules_text:
            common += (
                "\n\n【全局页面生成规范】命中本章节后必须遵守的正向生成要求（优先级高于检查规则）：\n"
                f"{page_generation_rules_text}"
            )
        if custom_requirements and custom_requirements.strip():
            common += (
                "\n\n以下是用户额外提出的自定义要求，生成内容时必须遵循：\n"
                f"{custom_requirements.strip()}"
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
                "- **必须保持模板页的整体版面结构**：标题位置、装饰元素、背景色块等必须与模板一致\n"
                "- 在模板中图形占位区域的位置，用 SVG 基本图形元素（rect、line、path、text）绘制架构图或流程图\n"
                "- 图形区域的边界范围必须与模板中预留的图形区域一致，不要超出或缩小\n"
                "- 用矩形表示系统/模块，用线条和箭头表示连接关系\n"
                "- 每个矩形内填写系统名称，线条旁可标注接口类型\n"
                "- 新建系统用特殊颜色标识，现有系统用灰色或无填充\n"
                "- 联机接口用实线，批量接口用虚线\n"
                "- 图形元素必须使用 SVG 基本标签（rect、line、path、text），不要使用 image 标签\n"
                "- 模板中的标题文字样式（字体大小、颜色、位置）必须保持不变，只替换文字内容\n"
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
        page_generation_rules_text: str = "",
        custom_requirements: str = "",
    ) -> str:
        parts = [
            f"需求文本：\n{requirement_text.strip()}\n\n",
            f"当前是第 {page_no} 页，页面名称：{page_name}\n",
            f"页面类型：{page_type}\n",
            f"页面标题：{page_title}\n\n",
            f"模板页 SVG 内容（必须严格保持其版面结构、坐标、颜色、字体样式，只替换文字内容，不要保留占位说明文字）：\n{svg_content.strip()}\n\n",
        ]
        if page_generation_rules_text:
            parts.append(f"本章节必须遵守的生成规范：\n{page_generation_rules_text}\n\n")
        if custom_requirements and custom_requirements.strip():
            parts.append(f"用户自定义要求：\n{custom_requirements.strip()}\n\n")
        parts.append(
            "请根据需求文本的内容和上述生成规范，严格保持模板的版面结构、颜色方案和字体样式，"
            "只将模板中的占位文字和填写说明替换为实际内容，生成一个完整的 SVG。\n"
            "重要提醒：不要重新创造布局，必须复用模板中所有元素的坐标、尺寸、颜色和样式属性。"
        )
        return "".join(parts)

    def build_diagram_system_prompt(self, check_rules_text: str = "", page_generation_rules_text: str = "", custom_requirements: str = "") -> str:
        prompt = (
            "你是一个专业的系统架构/产品连接图 SVG 绘制助手。你的任务是根据需求文本，"
            "绘制一张独立的产品连接关系图（只输出图形本身，不输出整页 PPT 模板）。\n\n"
            f"{DIAGRAM_DRAWING_RULES}\n\n"
            "绘图步骤（必须遵循）：\n"
            "1. 从需求文本中提取所有产品/系统名称。\n"
            "2. 识别每个产品的属性：改造状态（需要改造 / 仅配合测试）、业务分类（渠道 / 业务 / 平台 / 后线）。\n"
            "3. 根据分类从左到右排列产品，按矩形绘制。\n"
            "4. 根据需求中的接口说明绘制连线：实线箭头（联机）、虚线箭头（批量）。\n"
            "5. 对明显的新增关系使用红色线条并在箭头旁标注“新增”。\n"
            "6. 将图形整体放在 viewBox 的下半部分，避免占用上半部分。\n"
            "7. 输出完整、可直接解析的 SVG 字符串。"
        )
        if check_rules_text:
            prompt += (
                "\n\n以下是该页面需要遵守的检查规则，生成图形时必须严格遵循：\n"
                f"{check_rules_text}"
            )
        if page_generation_rules_text:
            prompt += (
                "\n\n【全局页面生成规范】命中本章节后必须遵守的正向生成要求（优先级高于检查规则）：\n"
                f"{page_generation_rules_text}"
            )
        if custom_requirements and custom_requirements.strip():
            prompt += (
                "\n\n以下是用户额外提出的自定义要求，生成图形时必须遵循：\n"
                f"{custom_requirements.strip()}"
            )
        return prompt

    def build_diagram_user_prompt(
        self,
        requirement_text: str,
        page_no: int,
        page_name: str,
        page_title: str,
        page_generation_rules_text: str = "",
        custom_requirements: str = "",
    ) -> str:
        parts = [
            f"需求文本：\n{requirement_text.strip()}\n\n",
            f"当前是第 {page_no} 页，页面名称：{page_name}\n",
            f"页面标题：{page_title}\n\n",
        ]
        if page_generation_rules_text:
            parts.append(f"本章节必须遵守的生成规范：\n{page_generation_rules_text}\n\n")
        if custom_requirements and custom_requirements.strip():
            parts.append(f"用户自定义要求：\n{custom_requirements.strip()}\n\n")
        parts.append(
            "请根据需求文本中的产品列表、接口关系和上述生成规范，绘制一张产品连接关系图。\n"
            "只返回完整 SVG 代码，不要返回任何解释、markdown、代码块或整页 PPT 模板。"
        )
        return "".join(parts)
