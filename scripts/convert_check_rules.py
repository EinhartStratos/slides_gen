"""将 check_rules.txt 转换为结构化 check_rules.json。

解析逻辑：
1. 用 csv 模块解析 TSV，自动处理引号包裹的多行字段
2. 从"关键检查要点"列提取关键词
3. 根据"检查项"大类和内容推断 page_purposes
4. 输出 JSON 供人工 review
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

INPUT_FILE = Path(__file__).resolve().parent.parent / "check_rules.txt"
OUTPUT_FILE = Path(__file__).resolve().parent.parent / "app" / "config" / "check_rules.json"


def extract_keywords(category: str, check_point: str, requirement: str) -> list[str]:
    """从检查要点中提取用于匹配模板页名的关键词。"""
    keywords: list[str] = []

    # 1. 去掉常见前缀
    cleaned = check_point
    for prefix in ("文档标准化-", "检查", "是否"):
        cleaned = cleaned.replace(prefix, "")
    cleaned = cleaned.strip("。.，,")

    # 2. 如果清洗后仍有内容，作为关键词
    if cleaned and len(cleaned) >= 2:
        keywords.append(cleaned)

    # 3. 根据特定模式补充关键词
    text = check_point + requirement

    # 架构图相关
    if "架构图" in text:
        keywords.extend(["架构图", "整体架构", "应用架构"])
    if "逻辑架构" in text:
        keywords.append("逻辑架构")
    if "部署架构" in text or "逻辑部署" in text:
        keywords.extend(["部署架构", "逻辑部署"])
    if "数据架构" in text:
        keywords.append("数据架构")
    if "技术架构" in text:
        keywords.append("技术架构")
    if "安全架构" in text:
        keywords.append("安全架构")

    # 需求相关
    if "需求背景" in text:
        keywords.append("需求背景")
    if "需求概貌" in text or "需求概述" in text:
        keywords.extend(["需求概述", "需求概貌", "需求"])
    if "现状分析" in text:
        keywords.append("现状分析")
    if "项目方案" in text or "方案要点" in text or "方案概述" in text:
        keywords.extend(["项目方案", "方案要点", "方案概述"])
    if "假设和约束" in text or "假设" in text:
        keywords.append("假设")
    if "分级分类" in text:
        keywords.append("分级分类")
    if "方案变更" in text:
        keywords.append("方案变更")
    if "缺陷修订" in text:
        keywords.append("缺陷修订")
    if "无二义性" in text:
        keywords.append("需求")
    if "覆盖机构范围" in text:
        keywords.append("需求")
    if "互联网外联" in text or "新技术使用" in text:
        keywords.append("需求")
    if "关联关系" in text and "需求" in text:
        keywords.append("需求")

    # 工作量相关
    if "工作量" in text:
        keywords.append("工作量")
    if "实施计划" in text:
        keywords.append("实施计划")
    if "预算" in text:
        keywords.append("预算")

    # 架构决策
    if "架构决策" in text:
        keywords.append("架构决策")

    # 整体架构设计类规则补充
    if category == "整体架构设计":
        keywords.extend(["整体架构", "架构图", "架构决策"])
        if "技术标准" in text or "规范" in text:
            keywords.append("架构图")
        if "架构规划" in text:
            keywords.append("架构图")
        if "架构原则" in text:
            keywords.append("架构决策")
        if "突破" in text or "过渡期" in text:
            keywords.append("架构决策")

    # 处理流程
    if "处理流程" in text or "业务流程" in text:
        keywords.append("处理流程")

    # 战略项目/信创
    if "战略项目" in text or "信创" in text:
        keywords.extend(["战略项目", "信创"])

    # 下线系统
    if "下线" in text:
        keywords.append("下线")

    # 外包
    if "外包" in text:
        keywords.append("外包")

    # 性能
    if "性能" in text:
        keywords.append("性能")

    # 灾备
    if "灾备" in text:
        keywords.append("灾备")

    # 数据迁移
    if "数据迁移" in text:
        keywords.append("数据迁移")

    # 数据备份
    if "数据备份" in text:
        keywords.append("数据备份")

    # 网络流量
    if "网络流量" in text:
        keywords.append("网络流量")

    # 大模型
    if "大模型" in text:
        keywords.append("大模型")

    # 高可用
    if "高可用" in text:
        keywords.append("高可用")

    # 技术栈
    if "技术栈" in text:
        keywords.append("技术栈")

    # 数据库
    if "数据库" in text:
        keywords.append("数据库")

    # 监控
    if "监控" in text:
        keywords.append("监控")

    # 入侵/安全
    if "入侵" in text or "安全组件" in text or "安全属性" in text:
        keywords.append("安全")

    # 监管
    if "监管" in text:
        keywords.append("监管")

    # 性能
    if "性能" in text:
        keywords.append("性能")

    # 字符集
    if "字符集" in text or "Unicode" in text or "UTF-8" in text:
        keywords.append("字符集")

    # 第三方外联
    if "第三方" in text or "外联" in text:
        keywords.append("外联")
    if "外部系统" in text or "对接" in text:
        keywords.append("外联")

    # 强制更新
    if "强制更新" in text or "客户端APP" in text or "客户端" in text:
        keywords.extend(["APP", "客户端"])

    # CDN
    if "CDN" in text:
        keywords.append("CDN")
    if "静态资源" in text or "流媒体" in text or "带宽" in text:
        keywords.append("CDN")

    # 三大平台
    if "三大平台" in text or "鸿鹄" in text or "星汉" in text or "瀚海" in text:
        keywords.extend(["平台", "鸿鹄", "星汉", "瀚海"])

    # 技术路线/选型
    if "技术路线" in text or "选型" in text or "POC" in text:
        keywords.extend(["技术栈", "选型", "POC"])

    # 数据副本/采集
    if "数据副本" in text or "采集" in text:
        keywords.extend(["数据", "采集"])
    if "P7" in text and "P8" in text:
        keywords.append("P7")

    # 数据接口
    if "数据接口" in text or "P6" in text:
        keywords.extend(["数据", "接口", "P6"])

    # 数据入湖入仓
    if "入湖" in text or "入仓" in text:
        keywords.extend(["数据", "入湖", "入仓"])
    if "颗粒归仓" in text:
        keywords.append("入湖")

    # 数据落标
    if "落标" in text or "数据字典" in text:
        keywords.extend(["数据", "落标", "数据字典"])

    # 数据生命周期
    if "生命周期" in text or "客户信息" in text:
        keywords.extend(["安全", "客户信息", "生命周期"])

    # 自主化
    if "自主化" in text:
        keywords.extend(["外包", "自主化", "技术转移"])

    # 安全组件
    if "安全组件" in text or "人机识别" in text or "设备指纹" in text:
        keywords.extend(["安全", "人机识别", "设备指纹"])

    # 关键安全属性
    if "安全属性" in text or "信息数据安全" in text:
        keywords.extend(["安全", "安全等级"])

    # 性能设计
    if "性能设计" in text or "性能方案" in text:
        keywords.extend(["性能", "压测", "容量"])

    # 新建系统
    if "新建系统" in text or "新建/架构调整" in text:
        keywords.extend(["新建", "基本信息"])

    # 下线系统
    if "下线" in text:
        keywords.extend(["下线", "待下线"])

    # 文件修订
    if "修订历史" in text or "文件修订" in text:
        keywords.append("修订历史")

    # 附录
    if "附录" in text or "仿真并行" in text or "旁路验证" in text:
        keywords.extend(["附录", "仿真", "旁路"])

    # 大模型场景
    if "大模型" in text and "场景" in text:
        keywords.append("大模型场景")

    # 按大类补充关键词（仅补充具体关键词，不补宽泛词避免过度匹配）
    if category == "整体架构设计":
        keywords.append("整体架构")
    if category == "技术架构设计":
        keywords.append("技术架构")
    if category == "安全架构设计":
        keywords.append("安全架构")
    if category == "数据架构设计":
        keywords.append("数据架构")
    if category == "应用架构设计":
        keywords.append("应用架构")
    if category == "工作量及实施计划":
        keywords.extend(["工作量", "实施计划"])
    if category == "文档标准化":
        keywords.extend(["需求背景", "需求概述", "项目方案", "现状分析"])
    if category == "非功能设计":
        keywords.extend(["技术架构", "性能"])

    # 去重并保持顺序
    seen = set()
    unique = []
    for kw in keywords:
        if kw not in seen and len(kw) >= 2:
            seen.add(kw)
            unique.append(kw)
    return unique


def infer_page_purposes(category: str, check_point: str, requirement: str) -> list[str]:
    """根据规则内容推断适用的页面类型。

    只有规则内容明确提到图相关的才加 diagram。
    表格相关的加 table。
    默认都包含 text。
    """
    text = check_point + requirement
    purposes: list[str] = ["text"]

    # 只有明确提到图/架构图/流程图/部署图才加 diagram
    if any(kw in text for kw in ["架构图", "流程图", "部署图", "图形", "画图", "示意图", "逻辑架构图"]):
        purposes.append("diagram")

    # 如果提到表格/工作量/预算/费用/占比/时间表才加 table
    if any(kw in text for kw in ["表格", "工作量", "预算", "费用", "占比", "时间表"]):
        purposes.append("table")
    else:
        # 默认也包含 table，因为大多数规则也适用于表格类页面
        purposes.append("table")

    # 去重
    seen = set()
    unique = []
    for p in purposes:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def convert() -> None:
    """执行转换。"""
    rules: list[dict] = []

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t", quotechar='"')
        header = next(reader)  # 跳过表行

        for i, row in enumerate(reader, start=1):
            if len(row) < 3:
                print(f"  [WARN] 第 {i} 行列数不足，跳过: {row}")
                continue

            category = row[0].strip()
            check_point = row[1].strip()
            requirement = row[2].strip()

            if not category or not check_point:
                print(f"  [WARN] 第 {i} 行有空字段，跳过: {row}")
                continue

            keywords = extract_keywords(category, check_point, requirement)
            page_purposes = infer_page_purposes(category, check_point, requirement)

            rule = {
                "id": f"rule_{i:03d}",
                "category": category,
                "check_point": check_point,
                "requirement": requirement,
                "keywords": keywords,
                "page_purposes": page_purposes,
            }
            rules.append(rule)

    # 写出 JSON
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(rules, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"转换完成: {len(rules)} 条规则 → {OUTPUT_FILE}")

    # 统计
    categories = {}
    no_keywords = []
    for r in rules:
        cat = r["category"]
        categories[cat] = categories.get(cat, 0) + 1
        if not r["keywords"]:
            no_keywords.append(f"  {r['id']} [{cat}] {r['check_point']}")

    print("\n按大类统计:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count} 条")

    if no_keywords:
        print(f"\n[WARN] {len(no_keywords)} 条规则未提取到关键词:")
        for line in no_keywords:
            print(line)
    else:
        print("\n所有规则均提取到关键词 ✓")


if __name__ == "__main__":
    convert()
