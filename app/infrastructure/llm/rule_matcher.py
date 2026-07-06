"""检查规则匹配器。

根据页面信息（页名、页面用途、元素内容）从 check_rules.json 中匹配适用的规则。
匹配策略：
1. 专有关键词匹配页名
2. 专有关键词匹配元素内容
3. 大类关键词仅匹配页名（作为 fallback，避免遗漏）
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 大类关键词：过于宽泛，只用于页名匹配，不用于元素内容匹配
BROAD_KEYWORDS = frozenset({
    "技术架构", "应用架构", "安全架构", "数据架构", "整体架构",
    "需求背景", "需求概述", "项目方案", "现状分析",
    "工作量", "实施计划", "新建", "基本信息",
    "架构图", "架构决策",
    "需求", "数据", "安全", "外包", "平台", "技术栈", "性能",
})


class RuleMatcher:
    """检查规则匹配器，加载 check_rules.json 并按页面匹配规则。"""

    def __init__(self, rules: list[dict[str, Any]]) -> None:
        self._rules = rules

    @classmethod
    def from_file(cls, rules_path: str | Path) -> "RuleMatcher":
        """从 JSON 文件加载规则。"""
        path = Path(rules_path)
        if not path.exists():
            logger.warning("检查规则文件不存在: %s，将使用空规则列表", path)
            return cls(rules=[])
        rules = json.loads(path.read_text(encoding="utf-8"))
        logger.info("已加载 %d 条检查规则: %s", len(rules), path)
        return cls(rules=rules)

    @property
    def rules(self) -> list[dict[str, Any]]:
        return self._rules

    def match(
        self,
        page_name: str,
        page_purpose: str,
        element_text: str = "",
    ) -> list[dict[str, Any]]:
        """匹配适用于该页面的检查规则。

        Args:
            page_name: 页面名称
            page_purpose: 页面用途（text/diagram/table）
            element_text: 页面元素的文本内容（content_requirement + default_text 拼接）
        Returns:
            匹配到的规则列表
        """
        if not self._rules:
            return []

        has_element_text = bool(element_text.strip())
        matched: list[dict[str, Any]] = []

        for rule in self._rules:
            # 按页面用途过滤
            if page_purpose not in rule.get("page_purposes", []):
                continue

            keywords = rule.get("keywords", [])
            specific_keywords = [kw for kw in keywords if kw not in BROAD_KEYWORDS]
            broad_keywords = [kw for kw in keywords if kw in BROAD_KEYWORDS]

            # 1. 专有关键词匹配页名
            name_specific_hit = any(kw in page_name for kw in specific_keywords) if specific_keywords else False

            # 2. 专有关键词匹配元素内容
            elem_hit = False
            if has_element_text and specific_keywords:
                elem_hit = any(kw in element_text for kw in specific_keywords)

            # 3. 大类关键词匹配页名（仅当无元素内容匹配时作为 fallback）
            broad_name_hit = False
            if not elem_hit and broad_keywords:
                broad_name_hit = any(kw in page_name for kw in broad_keywords)

            if name_specific_hit or elem_hit or broad_name_hit:
                matched.append(rule)

        return matched

    def format_rules_for_prompt(self, rules: list[dict[str, Any]]) -> str:
        """将匹配到的规则格式化为提示词文本。"""
        if not rules:
            return ""
        lines: list[str] = []
        for rule in rules:
            check_point = rule.get("check_point", "")
            requirement = rule.get("requirement", "")
            lines.append(f"- [{check_point}] {requirement}")
        return "\n".join(lines)
