"""检查 check_rules.json 的最终质量。"""
import json

rules = json.load(open("app/config/check_rules.json", encoding="utf-8"))

print(f"总规则数: {len(rules)}")
print()

# page_purposes 统计
diagram_rules = [r for r in rules if "diagram" in r["page_purposes"]]
table_rules = [r for r in rules if "table" in r["page_purposes"]]
text_rules = [r for r in rules if "text" in r["page_purposes"]]
print(f"含 diagram 的规则: {len(diagram_rules)}")
for r in diagram_rules:
    print(f"  {r['id']} {r['check_point']}")
print(f"含 table 的规则: {len(table_rules)}")
print(f"含 text 的规则: {len(text_rules)}")
print()

# 检查每条规则的关键词
print("各规则关键词:")
for r in rules:
    print(f"  {r['id']} [{r['category']}] {r['check_point']}")
    print(f"    keywords({len(r['keywords'])}): {r['keywords']}")
    print(f"    purposes: {r['page_purposes']}")
