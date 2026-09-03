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
import re
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


class PageGenerationRuleMatcher:
    """全局页面生成规范匹配器，加载 page_generation_rules.json 并按模板章节标题匹配。"""

    def __init__(self, rules: list[dict[str, Any]]) -> None:
        self._rules = rules

    @classmethod
    def from_file(cls, rules_path: str | Path | None) -> "PageGenerationRuleMatcher":
        """从 JSON 文件加载全局页面生成规范。"""
        if not rules_path:
            logger.info("未配置 page_generation_rules_file，使用空规则列表")
            return cls(rules=[])
        path = Path(rules_path)
        if not path.exists():
            logger.warning("全局页面生成规范文件不存在: %s，将使用空规则列表", path)
            return cls(rules=[])
        data = json.loads(path.read_text(encoding="utf-8"))
        rules = data.get("rules", []) if isinstance(data, dict) else []
        logger.info("已加载 %d 条全局页面生成规范: %s", len(rules), path)
        return cls(rules=rules)

    @property
    def rules(self) -> list[dict[str, Any]]:
        return self._rules

    @staticmethod
    def _normalize_page_name(page_name: str, title_match: dict[str, Any]) -> str:
        """按 title_match 配置规范化页面名称。"""
        text = (page_name or "").strip()
        if title_match.get("normalize_whitespace", True):
            text = re.sub(r"\s+", " ", text)
        for suffix in title_match.get("ignore_suffixes", []):
            if suffix and text.endswith(suffix):
                text = text[: -len(suffix)].strip()
        return text

    @staticmethod
    def _match_keywords(mode: str, normalized: str, keywords: list[str]) -> bool:
        """根据 mode 匹配关键词。"""
        keywords = [kw for kw in keywords if kw]
        if not keywords:
            return True
        if mode == "all_contains":
            return all(kw in normalized for kw in keywords)
        if mode == "equals":
            return any(normalized == kw for kw in keywords)
        # 默认 any_contains
        return any(kw in normalized for kw in keywords)

    def match(
        self,
        page_name: str,
        apply_to: str,
        svg_content: str = "",
    ) -> list[dict[str, Any]]:
        """匹配适用于该页面的全局生成规范。

        Args:
            page_name: 页面名称（模板固定章节标题）
            apply_to: 当前阶段（planning/body/diagram）
            svg_content: 可选，页面 SVG 内容，用于在标题未匹配时二次兜底
        Returns:
            匹配到的规则列表，按 priority 升序排列
        """
        if not self._rules:
            return []

        matched: list[dict[str, Any]] = []
        fallback_matched: list[dict[str, Any]] = []

        for rule in self._rules:
            if not rule.get("enabled", True):
                continue
            if apply_to not in rule.get("apply_to", []):
                continue

            title_match = rule.get("title_match", {})
            mode = title_match.get("mode", "any_contains")
            keywords = title_match.get("keywords", [])
            normalized = self._normalize_page_name(page_name, title_match)

            # 1. 标题匹配
            if self._match_keywords(mode, normalized, keywords):
                matched.append(rule)
                continue

            # 2. SVG 内容兜底（仅当标题未命中且规则 keywords 在 svg 中出现）
            if svg_content and self._match_keywords(mode, svg_content, keywords):
                fallback_matched.append(rule)

        # 合并并按 priority 升序；同优先级时标题匹配优先于 fallback
        all_matched = matched + [r for r in fallback_matched if r not in matched]
        all_matched.sort(key=lambda r: (r.get("priority", 100), matched.index(r) if r in matched else 9999))
        return all_matched

    def format_rules_for_prompt(self, rules: list[dict[str, Any]]) -> str:
        """将匹配到的全局生成规范格式化为提示词文本。

        如果规则包含 example 字段，会作为该章节的 few-shot 示例追加。
        """
        if not rules:
            return ""
        lines: list[str] = []
        for rule in rules:
            instruction = rule.get("instruction", "")
            if not instruction:
                continue
            rule_id = rule.get("id", "")
            lines.append(f"- [{rule_id}] {instruction}")
            example = rule.get("example", "")
            if example:
                lines.append(f"  【{rule_id} 示例输出】：\n{example}")
        return "\n".join(lines)
