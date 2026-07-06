"""验证规则匹配覆盖率：对模板每一页打印匹配到的规则。

匹配逻辑：
1. 页名匹配：page_name 包含规则关键词
2. 元素内容匹配：元素的 content_requirement / default_text 包含规则关键词
3. page_purposes 过滤：规则的 page_purposes 需包含页面 page_purpose
"""
import json

rules = json.load(open("app/config/check_rules.json", encoding="utf-8"))
template = json.load(open("template_rules.json", encoding="utf-8"))


def get_page_element_text(page: dict) -> str:
    """拼接页面所有元素的文本内容，用于关键词匹配。"""
    texts = []
    for e in page.get("elements", []):
        for field in ("content_requirement", "default_text"):
            val = e.get(field, "")
            if val:
                texts.append(val)
    return " ".join(texts)


# 大类关键词集合：这些词太宽泛，只用于页名匹配，不用于元素内容匹配
BROAD_KEYWORDS = {"技术架构", "应用架构", "安全架构", "数据架构", "整体架构",
                  "需求背景", "需求概述", "项目方案", "现状分析",
                  "工作量", "实施计划", "新建", "基本信息",
                  "架构图", "架构决策",
                  "需求", "数据", "安全", "外包", "平台", "技术栈", "性能"}


def match(page_name, page_purpose, element_text):
    matched = []
    has_element_text = bool(element_text.strip())
    for r in rules:
        if page_purpose not in r.get("page_purposes", []):
            continue
        keywords = r.get("keywords", [])
        specific_keywords = [kw for kw in keywords if kw not in BROAD_KEYWORDS]
        broad_keywords = [kw for kw in keywords if kw in BROAD_KEYWORDS]

        # 1. 专有关键词匹配页名
        name_specific_hit = any(kw in page_name for kw in specific_keywords) if specific_keywords else False
        # 2. 专有关键词匹配元素内容
        elem_hit = False
        if has_element_text and specific_keywords:
            elem_hit = any(kw in element_text for kw in specific_keywords)
        # 3. 大类关键词匹配页名（始终启用，确保规则不会遗漏）
        broad_name_hit = any(kw in page_name for kw in broad_keywords) if broad_keywords else False

        if name_specific_hit or elem_hit or broad_name_hit:
            matched.append(r)
    return matched


print(f"规则总数: {len(rules)}")
print(f"模板页数: {len(template['pages'])}")
print()

total_matches = 0
no_match_pages = []
for p in template["pages"]:
    page_no = p["page_no"]
    page_name = p.get("page_name", "")
    page_purpose = p.get("page_purpose", "")
    element_text = get_page_element_text(p)
    matched = match(page_name, page_purpose, element_text)
    total_matches += len(matched)
    if matched:
        details = []
        for r in matched:
            keywords = r.get("keywords", [])
            name_hit = any(kw in page_name for kw in keywords)
            elem_hit = any(kw in element_text for kw in keywords)
            source = "页名" if name_hit else ""
            if elem_hit:
                source += "+元素" if source else "元素"
            details.append(f"{r['id']}({source})")
        print(f"page {page_no:2d} [{page_purpose:<7s}] {page_name:<30s} → {len(matched):2d} 条: {details}")
    else:
        print(f"page {page_no:2d} [{page_purpose:<7s}] {page_name:<30s} →  0 条 ⚠")
        no_match_pages.append((page_no, page_name, page_purpose))

print()
print(f"总匹配次数: {total_matches}")
print(f"无匹配页面: {len(no_match_pages)}")
for no, name, purpose in no_match_pages:
    print(f"  page {no}: {name} ({purpose})")

# 检查哪些规则从未被任何页面匹配
all_matched_ids = set()
for p in template["pages"]:
    element_text = get_page_element_text(p)
    for r in match(p.get("page_name", ""), p.get("page_purpose", ""), element_text):
        all_matched_ids.add(r["id"])
unmatched_rules = [r for r in rules if r["id"] not in all_matched_ids]
print(f"\n从未被匹配的规则: {len(unmatched_rules)}")
for r in unmatched_rules:
    print(f"  {r['id']} [{r['category']}] {r['check_point']} → keywords={r['keywords']} purposes={r['page_purposes']}")
