"""需求文本预处理器。

把前端合并上传的 docx/xlsx/plain 文本拆成几大块，
对每一块并发调用 LLM 只做“小范围检索+结构化”，
最后把多个小结果拼成一份干净的技术方案素材。

如果某类文档没有上传，对应字段留空，不报错。
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProcessedRequirement:
    """预处理后的需求对象。"""

    raw_text: str
    formatted_text: str
    chunks: dict[str, str] = field(default_factory=dict)


# 页面→数据源路由表：按模板页名关键词命中，把该页该看的文档块喂给它。
# 顺序即优先级；命中的块为空时自动忽略，全部缺失则不加 scoped context。
_PAGE_CHUNK_ROUTES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("封面", "项目技术方案汇报"), ("requirement_doc", "situation_doc", "pre_eval", "workload")),
    (("项目基本信息",), ("situation_doc", "requirement_doc", "pre_eval", "workload")),
    (("需求背景", "需求简述", "现状分析", "假设", "约束", "可行性"), ("requirement_doc",)),
    (("需求概述", "需求项"), ("requirement_doc", "pre_eval", "function_points", "situation_doc")),
    (("方案要点", "方案概述"), ("pre_eval", "situation_doc", "requirement_doc", "function_points")),
    (("各系统工作说明", "产品矩阵"), ("pre_eval", "workload", "situation_doc")),
    (("总工作量", "实施计划", "实施协同"), ("pre_eval", "workload", "situation_doc")),
    (("架构", "流程", "连接关系", "拓扑"), ("plain", "requirement_doc", "situation_doc")),
    (("分级分类评审",), ("workload", "pre_eval", "function_points")),
)


def build_scoped_context(
    chunks: dict[str, str] | None,
    page_name: str,
    *,
    max_chars_per_chunk: int = 30000,
) -> str:
    """按页名命中路由表，返回该页专属的文档块上下文（可为空）。"""
    if not chunks:
        return ""
    for keywords, chunk_keys in _PAGE_CHUNK_ROUTES:
        if not any(kw in page_name for kw in keywords):
            continue
        parts: list[str] = []
        for key in chunk_keys:
            text = (chunks.get(key) or "").strip()
            if text:
                parts.append(f"【{key}】\n\n" + text[:max_chars_per_chunk])
        return "\n\n".join(parts)
    return ""


class _ExtractTask:
    """单个小范围的提取任务。"""

    def __init__(
        self,
        name: str,
        chunk_keys: list[str],
        system_prompt: str,
        is_json: bool,
        result_key: str | None = None,
    ) -> None:
        self.name = name
        self.chunk_keys = chunk_keys
        self.system_prompt = system_prompt
        self.is_json = is_json
        self.result_key = result_key


# 每个任务只让 LLM 返回一小块内容，便于稳定解析。
_EXTRACT_TASKS: list[_ExtractTask] = [
    _ExtractTask(
        name="project_info",
        chunk_keys=["requirement_doc", "situation_doc", "docx", "pre_eval", "workload"],
        system_prompt=(
            "你正在从需求说明书、应用项目情况说明、预评估表、工作量估算表里提取项目基本信息。"
            "只输出一个 JSON 对象，字段为：项目名称、需求编号、主办部门、版本/日期、"
            "项目类型（常规/战略/敏态/紧急，默认常规）、项目牵头业务部门、项目牵头研发部门、"
            "软件中心牵头总经理室成员、软件中心项目经理、业务目标、技术目标。"
            "字段来源提示：项目类型/业务目标/技术目标看情况说明；研发部门/项目经理看工作量明细的实施部门与产品联系人，"
            "或预评估表的部门/联系人列；各部门列中主改造产品对应的部门为牵头研发部门。"
            "找不到的字段填空字符串，禁止编造。只输出 JSON，不要解释。"
        ),
        is_json=True,
        result_key="project_info",
    ),
    _ExtractTask(
        name="background",
        chunk_keys=["docx"],
        system_prompt=(
            "你正在从需求说明书里提取‘1.1 需求背景’。"
            "只输出一段不超过 300 字的中文摘要。如果未找到，输出空字符串。"
        ),
        is_json=False,
        result_key="需求背景",
    ),
    _ExtractTask(
        name="summary",
        chunk_keys=["docx"],
        system_prompt=(
            "你正在从需求说明书里提取‘1.2 需求简述/需求提要’。"
            "只输出一段不超过 400 字的中文摘要。如果未找到，输出空字符串。"
        ),
        is_json=False,
        result_key="需求简述",
    ),
    _ExtractTask(
        name="status",
        chunk_keys=["docx"],
        system_prompt=(
            "你正在从需求说明书里提取现状分析。"
            "只输出 JSON：{\"业务现状\": \"...\", \"系统现状\": \"...\"}。"
            "未找到的字段填空字符串。"
        ),
        is_json=True,
        result_key="status",
    ),
    _ExtractTask(
        name="requirement_items",
        chunk_keys=["workload", "function_points", "pre_eval"],
        system_prompt=(
            "你正在从需求说明书和工作量/功能点/预评估表中提取需求项清单。"
            "xlsx 文本格式是：每个 sheet 以 'sheet-name: 名称\\nCSV content:\\n' 开头，后面是逗号分隔的表格行。"
            "请优先从工作量表的'需求项'列识别所有不同的需求项（按名称去重），预评估表'需求项'列同样可信（其行内'涉及产品/版本情况'直接给出改造与配合测试产品），从功能点表的'功能项编号/需求项/功能名称/功能描述'列补充每个需求项的主要处理流程和要点。"
            "必须输出 JSON 数组（最外层是 []），数组中包含多个对象，每个对象对应一个需求项。"
            "每个需求项包含：编号、名称、类型（功能类/流程类/数据类/非功能）、改造产品（数组）、配合测试产品（数组）、主要处理流程/要点。"
            "不要只输出一个对象，不要输出 Markdown 代码块。"
        ),
        is_json=True,
        result_key="requirement_items",
    ),
    _ExtractTask(
        name="product_matrix",
        chunk_keys=["workload", "pre_eval"],
        system_prompt=(
            "你正在从工作量估算表的'工作量明细'sheet或预评估表'预评估范围'sheet中提取产品工作说明。"
            "xlsx 文本格式是：每个 sheet 以 'sheet-name: 名称\\nCSV content:\\n' 开头，后面是逗号分隔的表格行。"
            "请按产品英文简称分组，识别所有涉及的产品（包括改造产品和仅配合测试产品），不要遗漏任何一行，一个产品一条记录，禁止合并多个产品为一行。"
            "必须输出 JSON 数组（最外层是 []），每个元素对应一个产品，包含：产品英文、产品中文、实施类型（改造/仅配合测试/不涉及）、涉及需求项（数组）、功能改造要点（数组）、非功能改造要点（数组）、数据需求改造要求（数组）、工作量（人天）。"
            "不要输出单个对象，不要输出 Markdown 代码块。"
        ),
        is_json=True,
        result_key="product_matrix",
    ),
    _ExtractTask(
        name="workload_summary",
        chunk_keys=["workload", "pre_eval"],
        system_prompt=(
            "你正在从工作量估算表中提取总工作量。"
            "只输出 JSON：{\"总人天\": \"...\", \"总人年\": \"...\", \"自主工作量\": \"...\", \"外包/厂商工作量\": \"...\"}。"
            "找不到填空。"
        ),
        is_json=True,
        result_key="workload_summary",
    ),
    _ExtractTask(
        name="implementation_plan",
        chunk_keys=["docx", "situation_doc", "workload", "pre_eval"],
        system_prompt=(
            "你正在提取项目实施计划与投产批次安排。"
            "预评估表'备注'列写有每个需求项/产品的批次可行性结论（如'可4月独立批次实施''最早可于2608批次实施'），"
            "情况说明的'项目开发规划'章写有实施周期与计划批次，优先依据这两处。"
            "只输出 JSON 数组，每个元素：{\"批次/时间\": \"...\", \"投产内容\": \"...\", \"涉及产品\": [\"...\"]}。"
            "材料中完全没有批次或周期信息时输出空数组 []，禁止自行预估。只输出 JSON。"
        ),
        is_json=True,
        result_key="implementation_plan",
    ),
    _ExtractTask(
        name="solution_points",
        chunk_keys=["pre_eval", "situation_doc", "docx"],
        system_prompt=(
            "你正在提取按需求项组织的项目方案要点。"
            "优先使用预评估表：其'需求项'列（合并单元格，组首行才有值，同组行属同一需求项）给出需求项，"
            "同组各行的'涉及产品/版本情况（有版本=改造、配合测试=仅测试）/工作说明'给出该项的改造要点与涉及系统；"
            "情况说明'功能详细介绍'章与需求书'功能描述'章作补充。"
            "必须输出 JSON 数组（最外层是 []），每个元素对应一个需求项，包含："
            "名称、类型（功能类/流程类/数据类/非功能）、改造产品（数组）、配合测试产品（数组）、主要改造点（数组，业务级条目，不写接口级细节）、预计工作量。"
            "不要输出单个对象，不要输出 Markdown 代码块。没有需求项依据时输出空数组 []。"
        ),
        is_json=True,
        result_key="solution_points",
    ),
    _ExtractTask(
        name="relations",
        chunk_keys=["plain"],
        system_prompt=(
            "你正在从产品连接关系/画图要求文本中提取产品调用、数据流向。"
            "输出不超过 300 字的中文描述。未找到输出空字符串。"
        ),
        is_json=False,
        result_key="产品连接关系",
    ),
    _ExtractTask(
        name="constraints",
        chunk_keys=["docx"],
        system_prompt=(
            "你正在提取项目的假设、约束、风险。"
            "输出不超过 200 字的中文摘要。"
            "如果输入中没有相关内容，输出空字符串。"
            "不要输出任何图形/DOT/Mermaid/流程图代码，只输出纯文本。"
        ),
        is_json=False,
        result_key="假设和约束",
    ),
    _ExtractTask(
        name="decisions",
        chunk_keys=["docx", "plain"],
        system_prompt=(
            "你正在提取项目中的架构决策事项/待决策事项。"
            "输出不超过 200 字的中文摘要。"
            "如果输入中没有涉及架构决策/待决策内容，输出空字符串。"
            "不要输出任何图形/DOT/Mermaid/流程图代码，只输出纯文本。"
        ),
        is_json=False,
        result_key="架构决策/待决策事项",
    ),
    _ExtractTask(
        name="notes",
        chunk_keys=["docx", "xlsx", "plain"],
        system_prompt=(
            "你正在汇总输入材料中对 PPT 有价值但未归入其它字段的额外信息。"
            "输出不超过 300 字的中文摘要。没有则输出空字符串。"
            "不要输出任何图形/DOT/Mermaid/流程图代码，只输出纯文本。"
        ),
        is_json=False,
        result_key="备注",
    ),
]


class RequirementPreprocessor:
    """需求文本预处理器。"""

    def __init__(
        self,
        llm_client: Any | None = None,
        api_key: str | None = None,
        max_input_chars: int = 20000,
        max_concurrency: int = 3,
    ) -> None:
        self.llm_client = llm_client
        self.api_key = api_key
        self.max_input_chars = max_input_chars
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def preprocess(self, raw_text: str) -> ProcessedRequirement:
        """对合并后的需求文本进行分块、并发小范围提取并格式化。"""
        if not raw_text or not raw_text.strip():
            return ProcessedRequirement(raw_text=raw_text, formatted_text=raw_text)

        chunks = self._split_into_chunks(raw_text)
        if self.llm_client and self.llm_client.enabled and self.api_key:
            try:
                formatted = await self._llm_extract(chunks)
                # 合理性校验：提取结果异常短于原文时按拼接兜底，避免上游格式
                # 不符导致提取任务空转后产出近乎空的摘要（静默失败）
                if len(raw_text) > 5000 and len(formatted.strip()) < 500:
                    logger.warning(
                        "LLM 提取结果过短（%d 字 vs 原文 %d 字），回退到分块拼接",
                        len(formatted.strip()), len(raw_text),
                    )
                    formatted = self._fallback_format(chunks)
                return ProcessedRequirement(raw_text=raw_text, formatted_text=formatted, chunks=chunks)
            except Exception as exc:
                logger.warning("LLM 需求预处理失败，回退到拼接模式: %s", exc)

        formatted = self._fallback_format(chunks)
        return ProcessedRequirement(raw_text=raw_text, formatted_text=formatted, chunks=chunks)

    _CHUNK_KEYS = (
        "docx", "requirement_doc", "situation_doc",
        "xlsx", "workload", "function_points", "pre_eval", "plain",
    )

    # 应用项目情况说明的文件名/内容特征
    _SITUATION_DOC_HINTS = ("情况说明", "项目情况")
    # 预评估表的 sheet 名/表头特征
    _PRE_EVAL_SHEET_HINTS = ("预评估", "排期意见")

    @staticmethod
    def _split_into_chunks(raw_text: str) -> dict[str, str]:
        """把合并文本拆成分类型块。

        支持两种输入：
        1. JSON 信封拼接（{"result":..., "data":{"type","filename"}}）——按类型/文件名分块；
        2. 纯 content 拼接（非 JSON）——按内容嗅探分块，识别不出归 plain。
        """
        chunks: dict[str, str] = {key: "" for key in RequirementPreprocessor._CHUNK_KEYS}
        decoder = json.JSONDecoder()

        last_end = 0
        i = 0
        while i < len(raw_text):
            if raw_text[i] == "{":
                try:
                    data, end = decoder.raw_decode(raw_text, i)
                    if isinstance(data, dict) and isinstance(data.get("result"), str):
                        result = data["result"]
                        file_meta = data.get("data") or {}
                        file_type = file_meta.get("type", "")
                        filename = file_meta.get("filename") or ""
                        RequirementPreprocessor._distribute_file_content(
                            result, file_type=file_type, filename=filename, chunks=chunks,
                        )
                        if last_end < i:
                            RequirementPreprocessor._distribute_raw_text(
                                raw_text[last_end:i], chunks,
                            )
                        last_end = end
                        i = end
                        continue
                except ValueError:
                    pass
            i += 1

        if last_end < len(raw_text):
            RequirementPreprocessor._distribute_raw_text(raw_text[last_end:], chunks)

        for key in ("docx", "requirement_doc", "situation_doc", "plain"):
            text = chunks[key]
            text = text.replace("{项目名称}业务需求说明书", "")
            text = text.replace("{项目名称}需求书", "")
            text = text.replace("{项目名称}用户需求说明书", "")
            chunks[key] = text.strip()

        return chunks

    @staticmethod
    def _distribute_file_content(
        result: str,
        *,
        file_type: str,
        filename: str,
        chunks: dict[str, str],
    ) -> None:
        """按文件类型/文件名把单个 JSON 信封的 result 分配到对应块。"""
        if file_type == "docx":
            if any(hint in filename for hint in RequirementPreprocessor._SITUATION_DOC_HINTS):
                chunks["situation_doc"] += result + "\n\n"
            else:
                chunks["requirement_doc"] += result + "\n\n"
            chunks["docx"] += result + "\n\n"
        elif file_type == "xlsx":
            RequirementPreprocessor._split_xlsx_sheets(result, chunks)
        else:
            # 其他类型文件按内容嗅探（可能是 txt/画图要求等）
            RequirementPreprocessor._distribute_raw_text(result, chunks)

    @staticmethod
    def _distribute_raw_text(text: str, chunks: dict[str, str]) -> None:
        """对非 JSON 信封的裸文本按内容嗅探归类。"""
        text = text.strip()
        if not text:
            return
        if "sheet-name:" in text:
            # 含表格块的文本：拆 sheet，首段非 sheet 文本另行嗅探
            parts = text.split("sheet-name:")
            head = parts[0]
            RequirementPreprocessor._distribute_plain_or_doc(head, chunks)
            for part in parts[1:]:
                RequirementPreprocessor._split_xlsx_sheets("sheet-name:" + part, chunks)
            return
        RequirementPreprocessor._distribute_plain_or_doc(text, chunks)

    @staticmethod
    def _distribute_plain_or_doc(text: str, chunks: dict[str, str]) -> None:
        """纯文本归类：具备需求书特征的归 requirement_doc，否则 plain。"""
        text = text.strip()
        if not text:
            return
        head = text[:3000]
        if any(kw in head for kw in ("需求说明书", "需求编号", "主办部门", "业务需求")):
            chunks["requirement_doc"] += text + "\n\n"
            chunks["docx"] += text + "\n\n"
        else:
            chunks["plain"] += text + "\n\n"

    @staticmethod
    def _split_xlsx_sheets(result: str, chunks: dict[str, str]) -> None:
        """把 xlsx 转出的多个 sheet 拆成预评估/工作量/功能点/其他。"""
        parts = result.split("sheet-name:")
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if "\nCSV content:\n" not in part:
                chunks["xlsx"] += part + "\n\n"
                continue
            name, csv_text = part.split("\nCSV content:\n", 1)
            name = name.strip().lower()
            first_lines = "\n".join(csv_text.splitlines()[:8]).lower()
            # 预评估表必须先于 workload 判断——"预评估范围"含"评估"否则会误归 workload
            if (
                any(hint in name for hint in RequirementPreprocessor._PRE_EVAL_SHEET_HINTS)
                or ("需求项" in first_lines and "涉及产品" in first_lines)
            ):
                chunks["pre_eval"] += f"sheet-name: {name}\nCSV content:\n{csv_text}\n\n"
            elif "工作量" in name or "估算" in name or "评估" in name:
                chunks["workload"] += f"sheet-name: {name}\nCSV content:\n{csv_text}\n\n"
            elif "功能点" in name or "功能项编号" in first_lines or "fp-" in first_lines or "产品属性" in first_lines:
                chunks["function_points"] += f"sheet-name: {name}\nCSV content:\n{csv_text}\n\n"
            else:
                chunks["xlsx"] += f"sheet-name: {name}\nCSV content:\n{csv_text}\n\n"

    async def _llm_extract(self, chunks: dict[str, str]) -> str:
        """并发调用 LLM 完成多个小范围提取任务。"""
        if not self.llm_client or not self.api_key:
            raise RuntimeError("未提供 LLM 客户端或 api_key")

        async def _run_one(task: _ExtractTask) -> dict[str, Any]:
            source = self._join_chunks(chunks, task.chunk_keys)
            if not source.strip():
                return {"task": task, "result": None}
            async with self._semaphore:
                return await asyncio.to_thread(self._run_task, task, source)

        tasks = [_run_one(task) for task in _EXTRACT_TASKS]
        results = await asyncio.gather(*tasks)
        data = self._merge_results(results)
        self._apply_table_fallbacks(data, chunks)
        return self._format_extracted(data)

    def _join_chunks(self, chunks: dict[str, str], keys: list[str]) -> str:
        """拼接多个 chunk，并做长度截断。"""
        parts: list[str] = []
        for key in keys:
            text = chunks.get(key, "")
            if not text:
                continue
            parts.append(f"【{key}】\n\n" + text[: self.max_input_chars])
        return "\n\n".join(parts)

    def _run_task(self, task: _ExtractTask, source: str) -> dict[str, Any]:
        """同步调用 LLM 执行单个小任务。"""
        try:
            result = self.llm_client._call_llm(
                api_key=self.api_key,
                system_prompt=task.system_prompt,
                user_prompt=source,
                use_json=task.is_json,
                stream=False,
                model=None,
                enable_thinking=False,
            )
            return {"task": task, "result": self._parse_result(task, result)}
        except Exception as exc:
            logger.warning("预处理任务 %s 失败: %s", task.name, exc)
            return {"task": task, "result": None}

    @staticmethod
    def _parse_result(task: _ExtractTask, text: str) -> Any:
        """解析 LLM 返回结果。"""
        text = text.strip()
        if not text:
            return None
        if task.is_json:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return text

    @staticmethod
    def _merge_results(results: list[dict[str, Any]]) -> dict[str, Any]:
        """把多个小任务的结果合并成一个大字典，并处理常见的外层包裹。"""
        data: dict[str, Any] = {}

        def unwrap_list(value: Any, keys: tuple[str, ...]) -> list[Any] | None:
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for key in keys:
                    if key in value and isinstance(value[key], list):
                        return value[key]
            return None

        for r in results:
            task = r["task"]
            value = r["result"]
            if value is None:
                continue
            if task.result_key:
                data[task.result_key] = value
            if task.name == "project_info" and isinstance(value, dict):
                data.update(value)
            if task.name == "status" and isinstance(value, dict):
                data["现状分析"] = value
            if task.name == "requirement_items":
                items = unwrap_list(value, ("需求项清单", "需求项", "items", "requirement_items"))
                if not items and isinstance(value, dict) and ("编号" in value or "名称" in value):
                    items = [value]
                if items:
                    data["需求项清单"] = items
            if task.name == "product_matrix":
                matrix = unwrap_list(value, ("产品清单", "products", "产品", "product_matrix"))
                if not matrix and isinstance(value, dict) and ("产品英文" in value or "产品中文" in value):
                    matrix = [value]
                if matrix:
                    data["产品清单"] = matrix
            if task.name == "workload_summary" and isinstance(value, dict):
                data["项目总工作量"] = value
            if task.name == "implementation_plan":
                plans = unwrap_list(value, ("实施计划", "plans", "items", "implementation_plan"))
                if not plans and isinstance(value, dict) and ("批次/时间" in value or "投产内容" in value):
                    plans = [value]
                if plans:
                    data["实施计划"] = plans
            if task.name == "solution_points":
                points = unwrap_list(value, ("方案要点", "solution_points", "items", "需求项"))
                if not points and isinstance(value, dict) and ("名称" in value or "需求项" in value):
                    points = [value]
                if points:
                    data["方案要点"] = points
        return data

    @staticmethod
    def _extract_workload_csv(workload_text: str) -> str:
        """从 workload chunk 中取出'工作量明细' sheet 的 CSV 内容。"""
        for part in workload_text.split("sheet-name:"):
            part = part.strip()
            if not part or "\nCSV content:\n" not in part:
                continue
            name, csv_text = part.split("\nCSV content:\n", 1)
            if "工作量" in name:
                return csv_text
        return workload_text

    @staticmethod
    def _build_product_matrix_from_workload(workload_text: str) -> list[dict[str, Any]] | None:
        """从工作量明细表中解析产品清单（LLM 失败时的兜底）。"""
        csv_text = RequirementPreprocessor._extract_workload_csv(workload_text)
        if not csv_text.strip():
            return None

        try:
            reader = csv.reader(io.StringIO(csv_text))
            header: list[str] | None = None
            rows: list[list[str]] = []
            for row in reader:
                if not row:
                    continue
                if row[0].strip() == "序号" and "需求项" in row:
                    header = row
                    continue
                if header is None:
                    continue
                if row[0].strip() in ("", "说明(此行勿删)", "示例(此行勿删)"):
                    continue
                if len(row) < 33:
                    continue
                rows.append(row)

            if not header:
                return None

            def col(*names: str) -> int:
                for name in names:
                    if name in header:
                        return header.index(name)
                # 容错：按去括号归一化匹配（如"产品（英文简称）"≈"产品英文"）
                normalized = [re.sub(r"[（(].*?[)）]", "", h).strip() for h in header]
                for name in names:
                    bare = re.sub(r"[（(].*?[)）]", "", name).strip()
                    for i, h in enumerate(normalized):
                        if h == bare or (bare and bare in h):
                            return i
                return -1

            idx_en = col("产品英文", "产品英文简称", "产品（英文简称）")
            idx_cn = col("产品中文", "产品名称", "产品（中文名称）")
            idx_type = col("版本情况", "实施类型")
            idx_req = col("需求项")
            idx_total = col("合计（人天）", "产品工作量小计")

            # 表头可能把'产品工作量小计'合并，子列在第二行
            if idx_total < 0:
                try:
                    idx_total = header.index("产品工作量小计") + 3
                except ValueError:
                    idx_total = -1

            if idx_en < 0 or idx_type < 0:
                return None

            products: dict[str, dict[str, Any]] = {}
            for row in rows:
                en = row[idx_en].strip()
                # 部分表没有中文名列，用英文简称兜底
                cn = row[idx_cn].strip() if idx_cn >= 0 else en
                if not en:
                    continue
                if not cn:
                    cn = en
                req = row[idx_req].strip() if idx_req >= 0 else ""
                status = row[idx_type].strip()
                kind = "仅配合测试" if status == "仅配合测试" else "改造"

                total = 0
                if idx_total >= 0 and len(row) > idx_total:
                    try:
                        total = int(float(row[idx_total].strip() or "0"))
                    except ValueError:
                        total = 0

                if en not in products:
                    products[en] = {
                        "产品英文": en,
                        "产品中文": cn,
                        "实施类型": kind,
                        "涉及需求项": [],
                        "功能改造要点": [],
                        "非功能改造要点": [],
                        "数据需求改造要求": [],
                        "工作量（人天）": 0,
                    }

                if status == "仅配合测试":
                    if kind != products[en]["实施类型"]:
                        products[en]["实施类型"] = kind
                else:
                    products[en]["实施类型"] = "改造"

                if req and req not in products[en]["涉及需求项"]:
                    products[en]["涉及需求项"].append(req)
                    products[en]["功能改造要点"].append(req)

                products[en]["工作量（人天）"] += total

            return list(products.values())
        except Exception as exc:
            logger.warning("解析产品清单失败: %s", exc)
            return None

    @staticmethod
    def _extract_function_points_csv(function_points_text: str) -> str:
        """从 function_points chunk 中取出包含功能点明细的 sheet CSV。"""
        for part in function_points_text.split("sheet-name:"):
            part = part.strip()
            if not part or "\nCSV content:\n" not in part:
                continue
            name, csv_text = part.split("\nCSV content:\n", 1)
            first_lines = "\n".join(csv_text.splitlines()[:8])
            if "功能项编号" in first_lines:
                return csv_text
        return ""

    @staticmethod
    def _build_function_points_map(function_points_text: str) -> dict[str, list[str]]:
        """从功能点明细表建立 需求项 -> 功能名称列表 的映射。"""
        csv_text = RequirementPreprocessor._extract_function_points_csv(function_points_text)
        if not csv_text:
            return {}

        result: dict[str, list[str]] = {}
        try:
            reader = csv.reader(io.StringIO(csv_text))
            header: list[str] | None = None
            for row in reader:
                if not row:
                    continue
                if row[0].strip() == "功能项编号" and "需求项" in row:
                    header = row
                    continue
                if header is None:
                    continue
                if len(row) < 5:
                    continue
                if row[0].strip() in ("", "功能项编号"):
                    continue

                idx_req = header.index("需求项")
                idx_name = header.index("功能名称")
                idx_desc = header.index("功能描述")

                req = row[idx_req].strip()
                if not req:
                    continue
                name = row[idx_name].strip()
                desc = row[idx_desc].strip() if idx_desc >= 0 else ""
                text = f"{name}：{desc}" if desc and desc != name else name
                if text and text not in result.get(req, []):
                    result.setdefault(req, []).append(text)
        except Exception as exc:
            logger.warning("解析功能点明细失败: %s", exc)
        return result

    @staticmethod
    def _build_requirement_items_from_workload(
        workload_text: str,
        function_points_text: str = "",
    ) -> list[dict[str, Any]] | None:
        """从工作量明细表中解析需求项清单，并用功能点明细补充要点。"""
        csv_text = RequirementPreprocessor._extract_workload_csv(workload_text)
        if not csv_text.strip():
            return None

        fp_map = RequirementPreprocessor._build_function_points_map(function_points_text)

        try:
            reader = csv.reader(io.StringIO(csv_text))
            header: list[str] | None = None
            rows: list[list[str]] = []
            for row in reader:
                if not row:
                    continue
                if row[0].strip() == "序号" and "需求项" in row:
                    header = row
                    continue
                if header is None:
                    continue
                if row[0].strip() in ("", "说明(此行勿删)", "示例(此行勿删)"):
                    continue
                if len(row) < 10:
                    continue
                rows.append(row)

            if not header:
                return None

            def col(*names: str) -> int:
                for name in names:
                    if name in header:
                        return header.index(name)
                normalized = [re.sub(r"[（(].*?[)）]", "", h).strip() for h in header]
                for name in names:
                    bare = re.sub(r"[（(].*?[)）]", "", name).strip()
                    for i, h in enumerate(normalized):
                        if h == bare or (bare and bare in h):
                            return i
                return -1

            idx_req = col("需求项")
            idx_id = col("需求编号")
            idx_en = col("产品英文", "产品英文简称", "产品（英文简称）")
            idx_type = col("版本情况", "实施类型")
            if idx_req < 0:
                return None

            items: dict[str, dict[str, Any]] = {}
            for row in rows:
                req = row[idx_req].strip()
                if not req:
                    continue
                if req not in items:
                    code = row[idx_id].strip() if idx_id >= 0 else ""
                    points = fp_map.get(req, [])[:8]
                    items[req] = {
                        "编号": code,
                        "名称": req,
                        "类型": req.split("(")[-1].rstrip(")") if "(" in req else "功能类",
                        "改造产品": [],
                        "配合测试产品": [],
                        "主要处理流程/要点": "；".join(points),
                    }
                en = row[idx_en].strip() if idx_en >= 0 else ""
                status = row[idx_type].strip() if idx_type >= 0 else ""
                if status == "仅配合测试":
                    if en and en not in items[req]["配合测试产品"]:
                        items[req]["配合测试产品"].append(en)
                else:
                    if en and en not in items[req]["改造产品"]:
                        items[req]["改造产品"].append(en)

            return list(items.values())
        except Exception as exc:
            logger.warning("解析需求项清单失败: %s", exc)
            return None

    @staticmethod
    def _find_pre_eval_scope_csv(pre_eval_text: str) -> str:
        """从 pre_eval chunk 中找到'预评估范围'主表（表头含 需求项+涉及产品）。"""
        for part in pre_eval_text.split("sheet-name:"):
            part = part.strip()
            if not part or "\nCSV content:\n" not in part:
                continue
            name, csv_text = part.split("\nCSV content:\n", 1)
            first_lines = "\n".join(csv_text.splitlines()[:6])
            if "预评估" in name or ("需求项" in first_lines and "涉及产品" in first_lines):
                return csv_text
        return ""

    @staticmethod
    def _strip_req_suffix(name: str) -> str:
        """剥掉需求项名的'（功能类）'类后缀，兼容缺右括号与全角括号。"""
        return re.sub(r"[（(](功能类|流程类|数据类|非功能类?)[)）]?$", "", name).strip()

    @staticmethod
    def _parse_pre_eval(pre_eval_text: str) -> dict[str, Any] | None:
        """解析预评估表'预评估范围'sheet。

        行语义（业务已确认）：同一行的'涉及产品'由同位置'主产品/部门/团队'实施，
        工作量归属所在需求项；需求项为合并单元格，按上一非空值前向填充。
        费用类列（费用合计/费用（万元）/#REF!）整列忽略。
        """
        csv_text = RequirementPreprocessor._find_pre_eval_scope_csv(pre_eval_text)
        if not csv_text.strip():
            return None
        try:
            reader = csv.reader(io.StringIO(csv_text))
            rows = [row for row in reader if row and any(cell.strip() for cell in row)]
            if not rows:
                return None
            header_idx = None
            for idx, row in enumerate(rows[:10]):
                if "需求项" in row and "涉及产品" in row:
                    header_idx = idx
                    break
            if header_idx is None:
                return None
            header = rows[header_idx]

            def col(name: str) -> int:
                return header.index(name) if name in header else -1

            def col_contains(*keywords: str) -> int:
                for i, cell in enumerate(header):
                    if all(kw in cell for kw in keywords):
                        return i
                return -1

            idx_req = col("需求项")
            idx_product = col("涉及产品")
            idx_status = col("版本情况")
            idx_contact = col("联系人")
            idx_work = col("工作说明")
            idx_note = col("备注")
            idx_main = col("主产品")
            idx_dept = col("部门")
            idx_team = col("团队")
            idx_vendor = col("厂商")
            idx_dev_self = col_contains("开发", "自有")
            idx_dev_out = col_contains("开发", "外购")
            idx_test_self = col_contains("功能测试", "自有")
            idx_test_out = col_contains("功能测试", "外购")

            if idx_req < 0 or idx_product < 0:
                return None

            def num(row: list[str], i: int) -> int:
                if i < 0 or i >= len(row):
                    return 0
                try:
                    return int(float(row[i].strip() or "0"))
                except ValueError:
                    return 0

            def cell(row: list[str], i: int) -> str:
                return row[i].strip() if 0 <= i < len(row) else ""

            footer_markers = ("合计", "联系人", "自有人员", "开发外购", "测试外购", "外包")
            items: list[dict[str, Any]] = []
            totals: dict[str, Any] = {}
            contacts: list[str] = []
            current_req = ""
            footer_started = False
            for row in rows[header_idx + 1:]:
                first = cell(row, 0)
                if first and any(m in first for m in footer_markers):
                    footer_started = True
                if footer_started:
                    # 页脚区：只采集合计数字与业务联系人，不再生成需求项行
                    cells = [c.strip() for c in row]
                    if "联系人" in first:
                        contacts.extend(
                            c for c in re.split(r"[、，,;；：:]", " ".join(cells[1:4]))
                            if c and re.search(r"[一-鿿A-Za-z]", c)
                        )
                    elif not first and cell(row, idx_product) and "：" not in cell(row, idx_product):
                        # 联系人行的续行（首列为空，涉及产品列是姓名列表）
                        contacts.extend(
                            c for c in re.split(r"[、，,;；]", cell(row, idx_product))
                            if c and re.search(r"[一-鿿A-Za-z]", c)
                        )
                    for ci, c in enumerate(cells):
                        if "合计" in c and ci + 1 < len(cells) and re.fullmatch(r"\d+(\.\d+)?", cells[ci + 1] or ""):
                            totals[c] = cells[ci + 1]
                    continue
                if first:
                    current_req = first
                if not current_req:
                    continue
                if items and items[-1]["原始需求项名"] == current_req:
                    item_rows = items[-1]["rows"]
                else:
                    item_rows = []
                    items.append({
                        "需求项": RequirementPreprocessor._strip_req_suffix(current_req),
                        "原始需求项名": current_req,
                        "类型": "功能类",
                        "rows": item_rows,
                    })
                wl_dev_self = num(row, idx_dev_self)
                wl_dev_out = num(row, idx_dev_out)
                wl_test_self = num(row, idx_test_self)
                wl_test_out = num(row, idx_test_out)
                record = {
                    "涉及产品": cell(row, idx_product),
                    "版本情况": cell(row, idx_status),
                    "联系人": cell(row, idx_contact),
                    "工作说明": cell(row, idx_work),
                    "批次意见": cell(row, idx_note),
                    "主产品": cell(row, idx_main),
                    "部门": cell(row, idx_dept),
                    "团队": cell(row, idx_team),
                    "厂商": cell(row, idx_vendor),
                    "开发自有": wl_dev_self,
                    "开发外购": wl_dev_out,
                    "测试自有": wl_test_self,
                    "测试外购": wl_test_out,
                    "工作量合计": wl_dev_self + wl_dev_out + wl_test_self + wl_test_out,
                }
                if any([record["涉及产品"], record["工作说明"], record["主产品"], record["工作量合计"]]):
                    item_rows.append(record)
            if not items:
                return None
            return {"items": items, "totals": totals, "contacts": contacts}
        except Exception as exc:
            logger.warning("解析预评估表失败: %s", exc)
            return None

    @staticmethod
    def _pre_eval_requirement_items(parsed: dict[str, Any]) -> list[dict[str, Any]]:
        """预评估行 → 需求项清单格式（与工作量表兜底同构）。"""
        result: list[dict[str, Any]] = []
        for item in parsed.get("items", []):
            changed, test_only, points = [], [], []
            for row in item.get("rows", []):
                product = row.get("涉及产品") or ""
                work = row.get("工作说明") or ""
                if row.get("版本情况") == "配合测试":
                    if product and product not in test_only:
                        test_only.append(product)
                elif product and product not in changed:
                    changed.append(product)
                if work and work not in points and work not in ("配合测试", "配合提供逻辑及配合测试"):
                    points.append(work)
            result.append({
                "编号": "",
                "名称": item.get("需求项") or item.get("原始需求项名") or "",
                "类型": item.get("类型") or "功能类",
                "改造产品": changed,
                "配合测试产品": test_only,
                "主要处理流程/要点": "；".join(points[:8]),
            })
        return result

    @staticmethod
    def _pre_eval_product_matrix(parsed: dict[str, Any]) -> list[dict[str, Any]]:
        """预评估行 → 产品清单格式（一产品一行）。"""
        products: dict[str, dict[str, Any]] = {}
        for item in parsed.get("items", []):
            req_name = item.get("需求项") or ""
            for row in item.get("rows", []):
                product = row.get("涉及产品") or ""
                if not product:
                    continue
                entry = products.setdefault(product, {
                    "产品英文": product,
                    "产品中文": product,
                    "实施类型": "仅配合测试",
                    "涉及需求项": [],
                    "功能改造要点": [],
                    "非功能改造要点": [],
                    "数据需求改造要求": [],
                    "工作量（人天）": 0,
                })
                if row.get("版本情况") != "配合测试":
                    entry["实施类型"] = "改造"
                if req_name and req_name not in entry["涉及需求项"]:
                    entry["涉及需求项"].append(req_name)
                work = row.get("工作说明") or ""
                if work and work not in entry["功能改造要点"]:
                    entry["功能改造要点"].append(work)
                entry["工作量（人天）"] += int(row.get("工作量合计") or 0)
        return list(products.values())

    def _apply_table_fallbacks(self, data: dict[str, Any], chunks: dict[str, str]) -> None:
        """LLM 返回的表格类结果不完整时，用 xlsx 表解析兜底。"""
        # 预评估表是需求项/产品矩阵的更高优先级数据源
        pre_eval_parsed = None
        pre_eval_text = chunks.get("pre_eval", "")
        if pre_eval_text.strip():
            pre_eval_parsed = self._parse_pre_eval(pre_eval_text)
        if pre_eval_parsed:
            data["预评估需求项"] = self._pre_eval_requirement_items(pre_eval_parsed)
            eval_products = self._pre_eval_product_matrix(pre_eval_parsed)
            if eval_products:
                existing = data.get("产品清单")
                if not isinstance(existing, list) or len(eval_products) >= len(existing):
                    data["产品清单"] = eval_products
            existing_items = data.get("需求项清单")
            eval_items = data["预评估需求项"]
            if eval_items and (not isinstance(existing_items, list) or len(eval_items) >= len(existing_items)):
                data["需求项清单"] = eval_items
            if pre_eval_parsed.get("totals"):
                data.setdefault("预评估合计", pre_eval_parsed["totals"])
            if pre_eval_parsed.get("contacts"):
                data.setdefault("业务联系人", "、".join(pre_eval_parsed["contacts"]))
            # 备注列批次意见 → 实施计划素材
            batch_notes = [
                row.get("批次意见") or ""
                for item in pre_eval_parsed.get("items", [])
                for row in item.get("rows", [])
            ]
            batch_notes = [n for n in batch_notes if n.strip()]
            if batch_notes and not data.get("实施计划"):
                data["实施计划"] = batch_notes[:10]

        workload = chunks.get("workload", "")
        if not workload:
            return

        existing_matrix = data.get("产品清单")
        existing_matrix_len = len(existing_matrix) if isinstance(existing_matrix, list) else 0
        matrix = self._build_product_matrix_from_workload(workload)
        if matrix and len(matrix) > existing_matrix_len:
            data["产品清单"] = matrix

        existing_items = data.get("需求项清单")
        existing_items_len = len(existing_items) if isinstance(existing_items, list) else 0
        fp_text = chunks.get("function_points", "")
        items = self._build_requirement_items_from_workload(workload, fp_text)
        if items and len(items) > existing_items_len:
            data["需求项清单"] = items

    @staticmethod
    def _format_extracted(data: dict[str, Any]) -> str:
        """把合并后的结构化数据转成格式化文本。"""
        lines: list[str] = []

        def is_empty_like(value: Any) -> bool:
            if value is None:
                return True
            if isinstance(value, str):
                return value.strip() in ("", "空字符串", "(空)", "（空）", "null", "none", "无", "空")
            return False

        def put(title: str, value: Any) -> None:
            if is_empty_like(value):
                return
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"【{title}】{value}")

        put("项目名称", data.get("项目名称"))
        put("需求编号", data.get("需求编号"))
        put("主办部门", data.get("主办部门"))
        put("版本/日期", data.get("版本/日期"))
        put("项目类型", data.get("项目类型"))
        put("项目牵头业务部门", data.get("项目牵头业务部门"))
        put("项目牵头研发部门", data.get("项目牵头研发部门"))
        put("软件中心牵头总经理室成员", data.get("软件中心牵头总经理室成员"))
        put("软件中心项目经理", data.get("软件中心项目经理"))
        put("业务目标", data.get("业务目标"))
        put("技术目标", data.get("技术目标"))
        put("业务联系人", data.get("业务联系人"))
        put("需求背景", data.get("需求背景"))
        put("需求简述", data.get("需求简述"))

        status = data.get("现状分析") or {}
        put("业务现状", status.get("业务现状"))
        put("系统现状", status.get("系统现状"))

        put("产品清单", data.get("产品清单"))
        put("需求项清单", data.get("需求项清单"))
        put("预评估需求项", data.get("预评估需求项"))
        put("方案要点", data.get("方案要点"))
        put("项目总工作量", data.get("项目总工作量"))
        put("实施计划", data.get("实施计划"))
        put("产品连接关系", data.get("产品连接关系"))
        put("假设和约束", data.get("假设和约束"))
        put("架构决策/待决策事项", data.get("架构决策/待决策事项"))
        put("备注", data.get("备注"))

        return "\n\n".join(lines)

    @staticmethod
    def _fallback_format(chunks: dict[str, str]) -> str:
        """LLM 不可用时，只做分块拼接和简单降噪。"""
        parts: list[str] = []
        if chunks.get("docx"):
            parts.append("【需求说明书】\n\n" + chunks["docx"])
        if chunks.get("situation_doc"):
            parts.append("【应用项目情况说明】\n\n" + chunks["situation_doc"])
        if chunks.get("pre_eval"):
            parts.append("【预评估结果表】\n\n" + chunks["pre_eval"])
        if chunks.get("workload"):
            parts.append("【工作量估算表】\n\n" + chunks["workload"])
        if chunks.get("function_points"):
            parts.append("【功能点估算明细】\n\n" + chunks["function_points"])
        if chunks.get("xlsx"):
            parts.append("【其他表格】\n\n" + chunks["xlsx"])
        if chunks.get("plain"):
            parts.append("【其他说明】\n\n" + chunks["plain"])
        return "\n\n".join(parts)
