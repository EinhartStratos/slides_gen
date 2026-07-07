# 内容检查规则注入方案

## 一、背景

当前系统在生成 PPT 内容时，LLM 仅根据需求全文和模板规则生成内容，缺少对银行技术方案文档的规范化约束。

`check_rules.txt` 中包含 167 条检查规则，涵盖文档标准化、整体架构设计、应用架构设计、技术架构设计、数据架构设计、安全架构设计、非功能设计、工作量及实施计划等 8 个大类。这些规则与模板中的章节（如"需求背景"、"项目整体架构图"、"安全架构"等）有明确的对应关系。

**目标**：在生成每一页内容时，将相关的检查规则注入到 LLM 提示词中，使生成内容自动符合规范要求。

---

## 二、规则与模板章节的对应关系分析

`check_rules.txt` 中的规则按大类可对应到模板的以下章节：

| 规则大类 | 对应模板页码 | 对应模板章节名 | 页面类型 |
|---------|------------|-------------|---------|
| 文档标准化 | 9 | 需求背景 | text |
| 文档标准化 | 10 | 需求概述 | table |
| 文档标准化 | 11 | 现状分析 | diagram |
| 文档标准化 | 15 | 项目整体架构图及说明 | diagram |
| 文档标准化 | 22-27 | 应用架构（新建/架构调整系统） | diagram/text |
| 整体架构设计 | 15 | 项目整体架构图及说明 | diagram |
| 整体架构设计 | 44 | 架构决策事项 | text |
| 应用架构设计 | 21-34 | 新建/架构调整系统系列页面 | text/diagram/table |
| 应用架构设计 | 36 | 主要处理流程 | text |
| 应用架构设计 | 41 | 与战略项目（产品信创）的实施关系 | table |
| 应用架构设计 | 42 | 待下线系统功能改造情况说明 | table |
| 技术架构设计 | 24-34 | 技术架构系列页面 | text/table/diagram |
| 数据架构设计 | 23 | 数据架构 | table |
| 数据架构设计 | 29 | 技术架构（续，含数据迁移） | table |
| 安全架构设计 | 35 | 安全架构 | text |
| 非功能设计 | 28 | 技术架构（续，含性能设计） | text |
| 工作量及实施计划 | 37 | 各系统工作说明及工作量 | table |
| 工作量及实施计划 | 39 | 项目总工作量 | table |
| 工作量及实施计划 | 40 | 项目实施计划 | table |

**关键发现**：规则与模板章节的对应关系是"一对多"和"多对一"混合的。一条规则可能适用于多个页面，一个页面也可能需要多条规则。

---

## 三、方案对比

### 方案 A：全量注入（一股脑丢到提示词）

**做法**：将所有 167 条规则作为一个通用的"检查规范"段落，拼接到每页的 system prompt 或 user prompt 中。

**优点**：
- 实现最简单，只需修改 prompt builder
- 不需要数据库改动
- LLM 能看到全局规范，交叉引用能力强

**缺点**：
- 每页 prompt 增加 ~5000 字，48 页累计多消耗 ~24 万 token，成本显著增加
- 大量无关规则会干扰 LLM 注意力，可能导致生成质量下降
- 规则更新需要改代码重新部署

**适用场景**：规则数量少（<20 条）且通用性强的情况。

### 方案 B：数据库打标 + 按页查询注入（用户初步想法）

**做法**：新建数据库表存储规则，每条规则打上 `page_no` 和 `content_type`（text/diagram/table）标签，生成时按页码查出相关规则注入提示词。

**优点**：
- 规则与页面精准匹配，只注入相关规则，token 开销可控
- 规则可通过数据库管理界面维护，无需改代码
- 支持多模板不同规则

**缺点**：
- 需要建表、写迁移脚本、写 CRUD 接口
- 打标工作量大（167 条规则需要人工关联到 48 页）
- 如果模板变更（页码调整），需要重新打标

**适用场景**：规则数量多、需要精细管理、模板稳定的情况。

### 方案 C（推荐）：基于关键词的智能匹配 + 配置文件管理

**做法**：
1. 将 `check_rules.txt` 解析为结构化 JSON 配置文件，每条规则标注 `category`（大类）和 `keywords`（匹配关键词）
2. 在生成每页内容时，根据模板页的 `page_name` 和 `page_purpose` 自动匹配相关规则
3. 匹配到的规则拼接到 user prompt 中

**匹配逻辑示例**：
```
页面 "需求背景" → 匹配 keywords 包含 "需求背景" 的规则
页面 "项目整体架构图及说明" → 匹配 keywords 包含 "架构图" 或 "整体架构" 的规则
页面 "安全架构" → 匹配 category="安全架构设计" 的所有规则
```

**优点**：
- 不需要建表和数据库改动，用 JSON 配置文件管理
- 自动匹配，无需人工逐条打标
- 规则更新只需改配置文件
- token 开销可控，每页只注入 3-10 条相关规则
- 模板页名变更时，关键词匹配自动适应

**缺点**：
- 匹配精度依赖关键词设计，可能漏匹配或误匹配
- 需要一次性将 txt 转为结构化 JSON

**适用场景**：当前项目的最佳平衡点。

---

## 四、推荐方案（方案 C）详细设计

### 4.1 规则配置文件格式

新建 `app/config/check_rules.json`：

```json
[
  {
    "id": "rule_001",
    "category": "文档标准化",
    "check_point": "文档标准化-需求背景",
    "requirement": "需求背景：重点说明业务目标，体现业务的真实意图，阐述需求价值；",
    "keywords": ["需求背景"],
    "page_purposes": ["text"]
  },
  {
    "id": "rule_002",
    "category": "文档标准化",
    "check_point": "文档标准化-需求概貌",
    "requirement": "需求概貌：需求内容要点按条目进行提炼和概括，不可原文复制粘贴；",
    "keywords": ["需求概述", "需求概貌"],
    "page_purposes": ["text", "table"]
  },
  {
    "id": "rule_011",
    "category": "文档标准化",
    "check_point": "架构图是否缺失",
    "requirement": "架构图一般应包括项目整体架构图、系统逻辑架构图和逻辑部署图，从多角度全面描述项目的应用架构、技术架构、数据架构、安全架构。",
    "keywords": ["架构图", "整体架构", "应用架构", "逻辑架构", "部署架构"],
    "page_purposes": ["diagram"]
  }
]
```

**字段说明**：
- `id`：规则唯一标识
- `category`：规则大类（对应 check_rules.txt 的第一列）
- `check_point`：检查要点（对应第二列）
- `requirement`：具体要求（对应第三列）
- `keywords`：匹配关键词列表，用于与模板页名匹配
- `page_purposes`：适用的页面类型（text/diagram/table），用于二次过滤

### 4.2 规则匹配逻辑

新建 `app/infrastructure/llm/rule_matcher.py`：

```python
class RuleMatcher:
    """根据页面信息匹配检查规则。"""

    def __init__(self, rules: list[dict]):
        self.rules = rules

    def match(self, page_name: str, page_purpose: str) -> list[dict]:
        """返回与当前页面相关的规则列表。"""
        matched = []
        for rule in self.rules:
            # 页面类型过滤
            if page_purpose not in rule.get("page_purposes", []):
                continue
            # 关键词匹配：page_name 包含任一 keyword 即命中
            keywords = rule.get("keywords", [])
            if any(kw in page_name for kw in keywords):
                matched.append(rule)
        return matched
```

### 4.3 提示词注入方式

在 `structured_prompt_builder.py` 和 `prompt_builder.py` 中，将匹配到的规则拼接到 user prompt：

**结构化生成（structured_prompt_builder.py）**：

在 `build_structured_user_prompt` 中追加规则段落：

```
请根据下面的需求全文和单页模板规则生成该页内容。

【内容规范要求】（请严格遵守以下检查规则）
1. 需求背景：重点说明业务目标，体现业务的真实意图，阐述需求价值；
2. 无二义性：不能存在不明确、有争议的需求内容。
...

要求：
1. 先判断该页是否适合当前需求。
...
```

**SVG 生成（prompt_builder.py）**：

在 `build_generate_user_prompt` 中追加规则段落：

```
需求文本：
...

【图形规范要求】
1. 架图一般应包括项目整体架构图、系统逻辑架构图和逻辑部署图...
2. 整体架构图体现应用架构全景，总体描述各系统在整体架构中的角色和定位...

模板页 SVG 内容：
...
```

### 4.4 规则加载与初始化

在服务启动时加载规则配置文件：

```python
# app/services/bootstrap.py 中初始化
rules_path = ROOT_DIR / "app" / "config" / "check_rules.json"
if rules_path.exists():
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    rule_matcher = RuleMatcher(rules)
else:
    rule_matcher = RuleMatcher([])
```

通过依赖注入传递给 prompt builder。

### 4.5 规则转换脚本

编写一次性脚本 `scripts/convert_check_rules.py`，将 `check_rules.txt` 转换为 `check_rules.json`：

- 解析 TSV 格式（三列：检查项、关键检查要点、具体要求）
- 自动提取关键词：从"检查要点"列中提取核心词
- 根据"检查项"大类和"检查要点"内容，自动推断 `page_purposes` 和 `keywords`
- 生成结构化 JSON 文件

### 4.6 后续维护方式

- **新增规则**：在 `check_rules.json` 中添加新条目，填写 `keywords` 和 `page_purposes`
- **修改规则**：直接编辑 JSON 文件中对应条目的 `requirement` 字段
- **删除规则**：删除 JSON 文件中对应条目
- **查看匹配效果**：可编写测试脚本，输入页名和页面类型，打印匹配到的规则列表

---

## 五、需要修改的文件清单

| 文件 | 修改内容 |
|------|---------|
| `app/config/check_rules.json` | **新建**：规则配置文件（由脚本从 txt 转换） |
| `scripts/convert_check_rules.py` | **新建**：一次性转换脚本 |
| `app/infrastructure/llm/rule_matcher.py` | **新建**：规则匹配器 |
| `app/infrastructure/llm/structured_prompt_builder.py` | **修改**：`build_structured_user_prompt` 接收并注入规则 |
| `app/infrastructure/llm/prompt_builder.py` | **修改**：`build_generate_user_prompt` 接收并注入规则 |
| `app/infrastructure/llm/openai_like_client.py` | **修改**：在调用 prompt builder 时传入匹配的规则 |
| `app/services/orchestration_service.py` | **修改**：初始化 RuleMatcher 并传递给 LLM 客户端 |
| `app/services/bootstrap.py` | **修改**：启动时加载规则配置文件 |
| `tests/test_rule_matcher.py` | **新建**：规则匹配器的单元测试 |

---

## 六、Token 开销估算

| 方案 | 每页增加 token | 48 页总计 | 效果 |
|------|-------------|----------|------|
| 方案 A（全量注入） | ~2500 | ~120,000 | 规则过多，可能干扰生成 |
| 方案 B（数据库打标） | ~200-800 | ~10,000-38,000 | 精准但维护成本高 |
| 方案 C（关键词匹配） | ~200-800 | ~10,000-38,000 | 精准且维护简单 |

方案 C 每页通常匹配 3-10 条规则，每条约 50-100 字，增加约 200-800 token，对生成成本影响可控。

---

## 七、风险与注意事项

1. **匹配精度**：关键词匹配可能漏掉某些规则。建议首次使用时编写测试打印所有页面的匹配结果，人工确认覆盖率后调整关键词。

2. **规则冲突**：某些规则可能互相矛盾（如"简洁概括"vs"详细说明"）。LLM 通常能自行权衡，但如果出现问题，可在规则中添加 `priority` 字段控制优先级。

3. **模板变更**：如果模板页名变更，关键词匹配会自动适应新名称，但可能需要调整关键词列表。

4. **规则文件体积**：167 条规则转 JSON 后约 30-50KB，加载到内存无压力。

---

## 八、实施步骤

1. 编写 `scripts/convert_check_rules.py`，将 `check_rules.txt` 转为 `app/config/check_rules.json`
2. 编写 `app/infrastructure/llm/rule_matcher.py` 规则匹配器
3. 编写测试验证匹配覆盖率
4. 修改 prompt builder，在 user prompt 中注入匹配到的规则
5. 修改 orchestration_service 和 bootstrap，初始化 RuleMatcher
6. 修改 openai_like_client，在调用时传入匹配的规则
7. 全量测试，确认生成内容符合规范

## 九、实现状态

> **已实现**（2026-07）

以上所有步骤均已完成：

- ✅ `check_rules.json` 已生成，包含 66 条规则
- ✅ `RuleMatcher` 类已实现，支持专有关键词 + 大类关键词匹配
- ✅ `prompt_builder.py` 和 `structured_prompt_builder.py` 已支持注入 `check_rules_text` 和 `custom_requirements`
- ✅ `openai_like_client.py` 的 `plan_single_page`、`generate_page_svg`、`generate_page_content` 均已支持传递规则和自定义要求
- ✅ `orchestration_service.py` 在每页处理前匹配规则并传递
- ✅ `bootstrap.py` 已注入 `RuleMatcher`
- ✅ `CreateGenerationTaskRequest` 已增加 `custom_requirements` 字段
- ✅ 辅助脚本 `verify_rule_coverage.py`、`coverage_summary.py`、`check_json_quality.py` 已创建
