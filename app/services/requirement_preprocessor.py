"""需求文本预处理器。

把前端合并上传的 docx/xlsx/plain 文本拆成几大块，
对每一块并发调用 LLM 只做“小范围检索+结构化”，
最后把多个小结果拼成一份干净的技术方案素材。

如果某类文档没有上传，对应字段留空，不报错。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProcessedRequirement:
    """预处理后的需求对象。"""

    raw_text: str
    formatted_text: str
    chunks: dict[str, str] = field(default_factory=dict)


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
        chunk_keys=["docx"],
        system_prompt=(
            "你正在从需求说明书里提取项目基本信息。"
            "只输出一个 JSON 对象，字段为：项目名称、需求编号、主办部门、版本/日期。"
            "找不到的字段填空字符串。只输出 JSON，不要解释。"
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
        chunk_keys=["workload", "function_points"],
        system_prompt=(
            "你正在从工作量估算表和功能点估算表中提取需求项清单。"
            "xlsx 文本格式是：每个 sheet 以 'sheet-name: 名称\\nCSV content:\\n' 开头，后面是逗号分隔的表格行。"
            "请从工作量表的'需求项'列识别所有不同的需求项，从功能点表的'需求项/功能名称/功能描述'列补充主要处理流程和要点。"
            "必须输出 JSON 数组（最外层是 []），每个元素对应一个需求项，包含：编号、名称、类型（功能类/流程类/数据类/非功能）、改造产品（数组）、配合测试产品（数组）、主要处理流程/要点。"
            "不要输出单个对象，不要输出 Markdown 代码块。"
        ),
        is_json=True,
        result_key="requirement_items",
    ),
    _ExtractTask(
        name="product_matrix",
        chunk_keys=["workload"],
        system_prompt=(
            "你正在从工作量估算表的'工作量明细'sheet中提取产品工作说明。"
            "xlsx 文本格式是：每个 sheet 以 'sheet-name: 名称\\nCSV content:\\n' 开头，后面是逗号分隔的表格行。"
            "请按产品英文简称分组，识别所有涉及的产品（包括改造产品和仅配合测试产品），不要遗漏任何一行。"
            "必须输出 JSON 数组（最外层是 []），每个元素对应一个产品，包含：产品英文、产品中文、实施类型（改造/仅配合测试/不涉及）、涉及需求项（数组）、功能改造要点（数组）、非功能改造要点（数组）、数据需求改造要求（数组）、工作量（人天）。"
            "不要输出单个对象，不要输出 Markdown 代码块。"
        ),
        is_json=True,
        result_key="product_matrix",
    ),
    _ExtractTask(
        name="workload_summary",
        chunk_keys=["workload"],
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
        chunk_keys=["docx", "workload"],
        system_prompt=(
            "你正在提取项目实施计划。"
            "只输出 JSON 数组，每个元素：{\"批次/时间\": \"...\", \"投产内容\": \"...\", \"涉及产品\": [\"...\"]}。"
            "只输出 JSON。"
        ),
        is_json=True,
        result_key="implementation_plan",
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
                return ProcessedRequirement(raw_text=raw_text, formatted_text=formatted, chunks=chunks)
            except Exception as exc:
                logger.warning("LLM 需求预处理失败，回退到拼接模式: %s", exc)

        formatted = self._fallback_format(chunks)
        return ProcessedRequirement(raw_text=raw_text, formatted_text=formatted, chunks=chunks)

    @staticmethod
    def _split_into_chunks(raw_text: str) -> dict[str, str]:
        """把合并文本拆成 docx / xlsx 及其子表 / plain 块。"""
        chunks: dict[str, str] = {"docx": "", "xlsx": "", "workload": "", "function_points": "", "plain": ""}
        decoder = json.JSONDecoder()

        last_end = 0
        i = 0
        while i < len(raw_text):
            if raw_text[i] == "{":
                try:
                    data, end = decoder.raw_decode(raw_text, i)
                    if isinstance(data, dict) and isinstance(data.get("result"), str):
                        result = data["result"]
                        file_type = (data.get("data") or {}).get("type", "")
                        if file_type == "docx":
                            chunks["docx"] += result + "\n\n"
                        elif file_type == "xlsx":
                            RequirementPreprocessor._split_xlsx_sheets(result, chunks)
                        else:
                            chunks["plain"] += result + "\n\n"
                        if last_end < i:
                            chunks["plain"] += raw_text[last_end:i] + "\n\n"
                        last_end = end
                        i = end
                        continue
                except ValueError:
                    pass
            i += 1

        if last_end < len(raw_text):
            chunks["plain"] += raw_text[last_end:]

        for key in ("docx", "plain"):
            text = chunks[key]
            text = text.replace("{项目名称}业务需求说明书", "")
            text = text.replace("{项目名称}需求书", "")
            text = text.replace("{项目名称}用户需求说明书", "")
            chunks[key] = text.strip()

        return chunks

    @staticmethod
    def _split_xlsx_sheets(result: str, chunks: dict[str, str]) -> None:
        """把 xlsx 转出的多个 sheet 拆成工作量/功能点/其他。"""
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
            if "工作量" in name or "估算" in name or "评估" in name:
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
        return data

    @staticmethod
    def _format_extracted(data: dict[str, Any]) -> str:
        """把合并后的结构化数据转成格式化文本。"""
        lines: list[str] = []

        def put(title: str, value: Any) -> None:
            if value is None:
                return
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"【{title}】{value}")

        put("项目名称", data.get("项目名称"))
        put("需求编号", data.get("需求编号"))
        put("主办部门", data.get("主办部门"))
        put("版本/日期", data.get("版本/日期"))
        put("需求背景", data.get("需求背景"))
        put("需求简述", data.get("需求简述"))

        status = data.get("现状分析") or {}
        put("业务现状", status.get("业务现状"))
        put("系统现状", status.get("系统现状"))

        put("产品清单", data.get("产品清单"))
        put("需求项清单", data.get("需求项清单"))
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
        if chunks.get("workload"):
            parts.append("【工作量估算表】\n\n" + chunks["workload"])
        if chunks.get("function_points"):
            parts.append("【功能点估算明细】\n\n" + chunks["function_points"])
        if chunks.get("xlsx"):
            parts.append("【其他表格】\n\n" + chunks["xlsx"])
        if chunks.get("plain"):
            parts.append("【其他说明】\n\n" + chunks["plain"])
        return "\n\n".join(parts)
