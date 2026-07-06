"""输出验证报告的关键统计信息。"""
import json

rules = json.load(open("app/config/check_rules.json", encoding="utf-8"))
template = json.load(open("template_rules.json", encoding="utf-8"))

BROAD_KEYWORDS = {"技术架构", "应用架构", "安全架构", "数据架构", "整体架构",
                  "需求背景", "需求概述", "项目方案", "现状分析",
                  "工作量", "实施计划", "新建", "基本信息",
                  "架构图", "架构决策",
                  "需求", "数据", "安全", "外包", "平台", "技术栈", "性能"}


def get_page_element_text(page):
    texts = []
    for e in page.get("elements", []):
        for field in ("content_requirement", "default_text"):
            val = e.get(field, "")
            if val:
                texts.append(val)
    return " ".join(texts)


def match(page_name, page_purpose, element_text):
    matched = []
    has_element_text = bool(element_text.strip())
    for r in rules:
        if page_purpose not in r.get("page_purposes", []):
            continue
        keywords = r.get("keywords", [])
        specific_keywords = [kw for kw in keywords if kw not in BROAD_KEYWORDS]
        broad_keywords = [kw for kw in keywords if kw in BROAD_KEYWORDS]
        name_specific_hit = any(kw in page_name for kw in specific_keywords) if specific_keywords else False
        elem_hit = False
        if has_element_text and specific_keywords:
            elem_hit = any(kw in element_text for kw in specific_keywords)
        broad_name_hit = any(kw in page_name for kw in broad_keywords) if broad_keywords else False
        if name_specific_hit or elem_hit or broad_name_hit:
            matched.append(r)
    return matched


total_matches = 0
no_match_pages = []
for p in template["pages"]:
    element_text = get_page_element_text(p)
    matched = match(p.get("page_name", ""), p.get("page_purpose", ""), element_text)
    total_matches += len(matched)
    if not matched:
        no_match_pages.append((p["page_no"], p.get("page_name", ""), p.get("page_purpose", "")))

# 检查哪些规则从未被任何页面匹配
all_matched_ids = set()
for p in template["pages"]:
    element_text = get_page_element_text(p)
    for r in match(p.get("page_name", ""), p.get("page_purpose", ""), element_text):
        all_matched_ids.add(r["id"])
unmatched_rules = [r for r in rules if r["id"] not in all_matched_ids]

# 输出统计
print(f"=== 验证报告统计 ===")
print(f"规则总数: {len(rules)}")
print(f"模板页数: {len(template['pages'])}")
print(f"总匹配次数: {total_matches}")
print(f"无匹配页面数: {len(no_match_pages)}")
for no, name, purpose in no_match_pages:
    print(f"  page {no}: {name} ({purpose})")
print(f"从未被匹配的规则数: {len(unmatched_rules)}")
for r in unmatched_rules:
    print(f"  {r['id']} [{r['category']}] {r['check_point']}")

# 每页匹配数
print(f"\n=== 每页匹配数 ===")
for p in template["pages"]:
    element_text = get_page_element_text(p)
    matched = match(p.get("page_name", ""), p.get("page_purpose", ""), element_text)
    flag = " ⚠" if not matched else ""
    print(f"  page {p['page_no']:2d} [{p.get('page_purpose',''):7s}] {p.get('page_name',''):30s} -> {len(matched):2d} 条{flag}")
