import json, collections
path = r'C:\AMD\slides_gen_server\app\config\check_rules.json'
with open(path, encoding='utf-8') as f:
    rules = json.load(f)
out_lines = []
out_lines.append(f'rules count: {len(rules)}')
cats = collections.Counter(r.get('category') for r in rules)
out_lines.append(f'categories count: {len(cats)}')
for c, n in cats.most_common():
    out_lines.append(f'  {c}: {n}')
purposes = set(tuple(r.get('page_purposes', [])) for r in rules)
out_lines.append(f'page_purposes values: {purposes}')
out_lines.append(f'sample fields: {list(rules[0].keys())}')
# show first few rule ids and check_points per category
for c, _ in cats.most_common():
    out_lines.append(f'--- category: {c} ---')
    for r in rules:
        if r.get('category') == c:
            out_lines.append(f"  {r.get('id')}: {r.get('check_point')}")
with open(r'C:\AMD\slides_gen_server\inspect_rules_output.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out_lines))
