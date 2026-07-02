# 混合生成方案设计文档

## 1. 背景与问题

### 1.1 当前 SVG 方案的问题

当前 `slides_gen_server` 对每一页都使用 LLM 生成完整 SVG，然后通过 `svg_to_pptx` 转回可编辑 PPTX。存在三个核心问题：

1. **速度慢**：每页 SVG 生成耗时可能高达 15 分钟，一个 15 页的 PPT 可能需要数小时
2. **编辑性差**：SVG 转回 PPTX 后，每一行文字都变成单行小文本框，用户后续编辑非常困难
3. **无法拆页**：SVG 方案不支持内容超长时自动拆分到多页

### 1.2 旧方案 `pptx_gen` 的优势

旧项目 `pptx_gen` 采用"模板解析 → LLM 生成结构化 JSON → python-pptx 直接回填"的方式：

1. **速度快**：LLM 只输出结构化 JSON（文本内容、表格数据），不输出 SVG，生成耗时大幅降低
2. **编辑性好**：直接操作 PPTX 原生文本框和表格，保持模板格式，用户编辑方便
3. **自动拆页**：`PPTBuilder` 内置文本溢出检测和表格分页，内容过长自动拆成多页

### 1.3 SVG 方案的价值与适用范围

SVG 方案的核心价值是**生成可编辑的矢量形状**。当模型生成的图形不满足要求时，用户可以在 PPT 中直接微调形状。如果将 SVG 渲染成 PNG 再插入，就完全丧失了可编辑性，等于放弃了选择 SVG 方案的最大理由。

因此 SVG 方案**只用于真正需要复杂可编辑矢量图形的页面**（如架构图、流程图、时序图等 `diagram` 类型页面），其余页面（封面、目录、正文、表格、尾页）全部走结构化填充。

观察模板中的封面页和尾页 SVG：

- **封面页**（`slide_01.svg`）：只有"文档编号"、"中心/部门名称 20XX年X月"等大字号文本，无复杂图形
- **尾页**（`slide_45.svg`）：只有一个色块背景 + "感谢聆听，敬请指正！"大字号文本

这些页面完全可以用结构化填充处理，不需要 SVG。

## 2. 方案概述：按页面类型混合生成

### 2.1 核心思路

在编排阶段，根据每页的 `page_type` 决定使用哪种生成方式：

| 页面类型 | 生成方式 | 说明 |
|----------|----------|------|
| `cover` | 结构化填充 | 封面：大字号文本 + 简单背景，无复杂图形 |
| `toc` | 结构化填充 | 目录：文本为主 |
| `content` | 结构化填充 | 正文：文本/表格，速度快、编辑性好、支持拆页 |
| `diagram` | SVG 生成 | 图形页：需要可编辑矢量形状，保留 SVG→DrawingML 转换 |
| `end` | 结构化填充 | 尾页：大字号文本 + 简单背景，无复杂图形 |

> 只有 `diagram` 类型走 SVG 路径，其余全部走结构化填充。具体哪些 `page_type` 走 SVG 可通过配置调整。

### 2.2 架构图

```text
run_task()
├─ 加载模板 PPTX
├─ 模板解析（TemplateRuleParser）→ TemplateRules JSON
├─ 并发提交所有页面到 ThreadPoolExecutor
│  └─ _process_one_page(page_no)
│     ├─ 规划（plan_single_page）→ page_type
│     ├─ 判断生成方式
│     │   ├─ SVG 路径（diagram）
│     │   │   ├─ generate_page_svg → SVG 文本
│     │   │   └─ 保存 SVG 文件到 svg_final/
│     │   └─ 结构化路径（cover/toc/content/end）
│     │       ├─ generate_page_content → 结构化 JSON
│     │       └─ 保存 JSON 到 structured_results/
│     └─ 更新进度
├─ 合并所有页面 → 导出最终 PPTX（见第 5 节详细描述）
└─ 上传 FTP
```

### 2.3 与当前架构的融合点

当前架构的 LLM 调用链路：
```
orchestration_service → slide_generation_service → openai_like_client
```

融合后的链路：
```
orchestration_service
  ├─ slide_generation_service（SVG 路径，保持不变）
  └─ pptx_builder_service（结构化路径，新增）
      └─ openai_like_client（复用，新增 generate_page_content 方法）
```

## 3. 需要从旧方案移过来的功能模块

### 3.1 模板规则解析器（TemplateRuleParser）

**来源**：`pptx_gen/template/parser.py`（约 485 行）

**功能**：解析 PPTX 模板，提取每页的元素规则（文本框位置、表格结构、图片占位等），输出 `TemplateRules` JSON。

**移过来的原因**：结构化填充需要知道模板中每个元素的 `shape_id`、`bbox`、`type`、`style` 等信息才能回填。

**目标位置**：`app/infrastructure/ppt_master/template_rule_parser.py`

**依赖**：`python-pptx`（已有）、`xml.etree.ElementTree`（标准库）

**需要适配的改动**：
- 去掉对 `pptx_gen.schemas` 的引用，数据模型改为使用 `app/schemas/common.py` 的 `SchemaModel` 基类
- 输出的 `TemplateRules` 存储到任务工作区 `analysis/template_rules.json`

### 3.2 PPT 构建器（PPTBuilder）

**来源**：`pptx_gen/ppt/builder.py`（约 656 行）

**功能**：读取模板规则 JSON + LLM 生成的页面结果 JSON，直接在模板 PPTX 上回填文本、表格，支持自动拆页。

**移过来的原因**：这是结构化填充的核心引擎，负责将 LLM 输出的文本/表格数据写入 PPTX 原生元素。

**目标位置**：`app/infrastructure/ppt_master/pptx_builder.py`

**依赖**：`python-pptx`（已有）

**需要适配的改动**：
- 去掉对 `pptx_gen.schemas` 的引用，改用新定义的 Pydantic 模型
- 去掉图片/Mermaid 相关逻辑（`_place_image` 等），图片页面由 SVG 路径处理
- `build()` 方法改为接收内存中的数据结构，而非文件路径
- 拆页逻辑保留，这是结构化方案的核心优势

### 3.3 结构化内容生成的 Prompt

**来源**：`pptx_gen/llm/prompts.py`（约 97 行）

**功能**：构建 system prompt 和 user prompt，让 LLM 输出结构化 JSON（文本内容、表格数据），而非 SVG。

**目标位置**：`app/infrastructure/llm/structured_prompt_builder.py`

**需要适配的改动**：
- 去掉 Mermaid 相关部分（diagram 页面由 SVG 路径处理）
- 只保留文本和表格的 JSON 输出格式
- 与现有 `prompt_builder.py` 并行存在

### 3.4 数据模型

**来源**：`pptx_gen/schemas.py` 中 `GeneratedElement` 和 `PageGenerationResult`

**功能**：LLM 结构化生成的数据载体。

**目标位置**：`app/schemas/structured_generation.py`（新建）

**模型定义**：
```python
class GeneratedElement(SchemaModel):
    id: str                    # 对应模板元素 ID
    type: str                  # text / table
    content: str | None        # 文本内容
    headers: list[str] | None  # 表格表头
    rows: list[list[str]] | None  # 表格行数据

class StructuredPageResult(SchemaModel):
    page_no: int
    should_generate: bool
    skip_reason: str
    elements: list[GeneratedElement]
```

### 3.5 不需要移过来的模块

| 模块 | 原因 |
|------|------|
| `pptx_gen/llm/client.py` | 当前项目已有 `openai_like_client.py`，只需新增方法 |
| `pptx_gen/llm/generator.py` | 当前项目已有并发编排，不需重复 |
| `pptx_gen/render/mermaid.py` | SVG 方案已覆盖图形渲染 |
| `pptx_gen/pipeline/runner.py` | 当前项目已有 `orchestration_service` |
| `pptx_gen/config.py` | 当前项目已有 `app/core/config.py` |
| `pptx_gen/cli.py` | 当前项目是 Web 服务，不需要 CLI |

## 4. 详细设计

### 4.1 新增文件清单

```text
app/
├─ infrastructure/
│  ├─ ppt_master/
│  │  ├─ template_rule_parser.py       # 从 pptx_gen/template/parser.py 移植
│  │  └─ pptx_builder.py               # 从 pptx_gen/ppt/builder.py 移植
│  └─ llm/
│     └─ structured_prompt_builder.py  # 从 pptx_gen/llm/prompts.py 移植
├─ schemas/
│  └─ structured_generation.py         # 新建：结构化生成数据模型
└─ services/
   └─ pptx_builder_service.py          # 新建：结构化填充编排服务
```

### 4.2 LLM 客户端改造

在 `OpenAILikePageGenerationClient` 中新增方法：

```python
def generate_page_content(
    self,
    api_key: str,
    requirement_text: str,
    page_no: int,
    page_name: str,
    page_rule: dict,          # 模板规则（来自 TemplateRuleParser）
    model: str | None = None,
    enable_thinking: bool = False,
) -> StructuredPageResult:
    """结构化内容生成：LLM 输出 JSON（文本/表格），不输出 SVG"""
    system_prompt = build_structured_system_prompt()
    user_prompt = build_structured_user_prompt(requirement_text, page_rule)
    content = self._call_llm(api_key, system_prompt, user_prompt, stream=True, model=model, ...)
    return self._parse_structured_result(content, page_no)
```

复用现有的 `_call_llm` 方法（含信号量、429 退避），不重复实现。

### 4.3 编排服务改造

在 `_process_one_page` 中增加分支判断：

```python
def _process_one_page(self, ...):
    # 1. 规划（不变）
    page_plan = self.slide_service.plan_single_page(...)

    # 2. 根据页面类型选择生成方式
    if page_plan.page_type in SVG_PAGE_TYPES:  # 只有 diagram
        # SVG 路径（现有逻辑不变）
        # generate_page_svg → 保存 SVG 文件到 svg_final/
        result = self.slide_service.generate_page_svg(...)
    else:
        # 结构化路径（新增）
        # generate_page_content → 保存 JSON 到 structured_results/
        result = self.pptx_builder_service.generate_page_content(
            api_key, requirement_text, page_no, page_rule, ...
        )

    # 3. 更新进度（不变）
```

### 4.4 配置项

#### 新增环境变量

```env
# 混合生成控制
SVG_PAGE_TYPES=diagram    # 使用 SVG 生成的页面类型（逗号分隔），默认只有 diagram
```

#### 配置字段

在 `app/core/config.py` 的 `Settings` 中新增：

```python
svg_page_types: str = "diagram"  # 使用 SVG 生成的页面类型
```

## 5. 最终 PPTX 整合方案（核心）

### 5.1 问题分析

两种生成路径产出不同形式的中间结果：

| 路径 | 中间产物 | 可编辑性 | 来源 |
|------|----------|----------|------|
| SVG 路径 | SVG 文件 → `convert_svg_to_slide_shapes()` → DrawingML slide XML | 可编辑形状 | `svg_to_pptx` 模块 |
| 结构化路径 | `StructuredPageResult` JSON | 原生文本框/表格 | `PPTBuilder` + python-pptx |

需要将这两种结果合并到**同一个 PPTX 文件**中，且所有页面都保持可编辑。

### 5.2 当前 SVG 导出流程

当前 `pptx_export_service.export()` 的流程：
1. 收集 `svg_final/` 目录下所有 `.svg` 文件（按文件名排序）
2. 调用 `SvgToPptxAdapter.export()` → `create_pptx_with_native_svg()`
3. `create_pptx_with_native_svg()` **从零创建** PPTX：
   - 创建空白 PPTX 包
   - 逐个 SVG 调用 `convert_svg_to_slide_shapes()` 生成 DrawingML slide XML
   - 将 slide XML 写入 PPTX 包
   - 保存最终 PPTX

关键点：当前流程**从零创建 PPTX**，不基于模板。结构化路径**需要基于模板 PPTX**操作原生 shape。两者起点不同。

### 5.3 整合方案：模板优先 + SVG slide 注入

**核心思路**：以模板 PPTX 为基础文件，结构化页面直接在模板 slide 上回填，SVG 页面用 `convert_svg_to_slide_shapes()` 生成 DrawingML XML 后替换对应 slide 的内容。

#### 整合流程

```text
Phase 1: 解析模板
  └─ TemplateRuleParser 解析模板 PPTX → TemplateRules JSON

Phase 2: 并发生成（已有逻辑）
  ├─ SVG 页面 → svg_final/page_NN.svg
  └─ 结构化页面 → structured_results/page_NN.json

Phase 3: 整合导出（新增 HybridPptxExporter）
  ├─ Step 1: 用 python-pptx 打开模板 PPTX 副本
  ├─ Step 2: 处理结构化页面
  │   ├─ 对每个结构化页面，用 PPTBuilder._fill_slide() 回填对应 slide
  │   ├─ 如果内容溢出 → 复制 slide 做拆页（PPTBuilder 已有此能力）
  │   └─ 如果 should_generate=false → 标记删除该 slide
  ├─ Step 3: 处理 SVG 页面
  │   ├─ 对每个 SVG 页面，调用 convert_svg_to_slide_shapes(svg_file)
  │   │   → 得到 DrawingML slide XML + media_files + rel_entries
  │   ├─ 清空对应 slide 的 <p:spTree> 中所有现有 shape
  │   ├─ 将转换后的 shape XML 插入 slide 的 <p:spTree>
  │   ├─ 将 media_files 写入 PPTX 的 media 目录
  │   └─ 添加对应的 relationship 条目
  ├─ Step 4: 处理跳过的页面
  │   └─ 删除 should_generate=false 的 slide
  ├─ Step 5: 重排 slide 顺序
  │   └─ 按原始页码顺序排列所有 slide（含拆页产生的新 slide）
  └─ Step 6: 保存最终 PPTX
```

#### 详细技术实现

**Step 2：结构化页面回填**

直接复用 `PPTBuilder` 的 `_fill_slide()` 方法。`PPTBuilder` 用 `python-pptx` 打开模板 PPTX 后：
- 通过 `shape.shape_id` 定位模板中的 shape
- 调用 `_set_text()` 填充文本框（保留模板字体、字号、对齐方式）
- 调用 `_fill_table()` 填充表格（保留模板表格样式）
- 调用 `_expand_result_for_overflow()` 检测内容溢出，自动复制 slide 拆页

拆页时通过 `_duplicate_slide_after()` 复制模板 slide 并回填剩余内容。

**Step 3：SVG 页面注入**

这是整合的关键技术点。`convert_svg_to_slide_shapes()` 返回：
- `slide_xml`：完整的 `<p:sld>` XML 字符串（包含 `<p:spTree>` 中的所有 shape）
- `media_files`：`dict[filename, bytes]`，SVG 中引用的图片等媒体文件
- `rel_entries`：relationship 条目列表

注入步骤：

```python
from lxml import etree
from pptx.oxml.ns import qn

def inject_svg_slide(presentation, slide_index, svg_file):
    """将 SVG 转换的 DrawingML 注入到模板 PPTX 的指定 slide"""
    # 1. 调用 svg_to_pptx 转换
    slide_xml, media_files, rel_entries, _ = convert_svg_to_slide_shapes(
        svg_file, slide_num=slide_index + 1
    )

    # 2. 解析转换后的 XML，提取 <p:spTree> 的子元素
    new_slide_root = etree.fromstring(slide_xml)
    new_sp_tree = new_slide_root.find(qn('p:spTree'))

    # 3. 获取目标 slide 的 <p:spTree>
    target_slide = presentation.slides[slide_index]
    target_sp_tree = target_slide._element.find(qn('p:cSld')).find(qn('p:spTree'))

    # 4. 删除目标 slide 中所有现有 shape（保留 nvGrpSpPr 和 grpSpPr）
    for child in list(target_sp_tree):
        tag = etree.QName(child).localname
        if tag not in ('nvGrpSpPr', 'grpSpPr'):
            target_sp_tree.remove(child)

    # 5. 将新 shape 插入目标 slide（跳过新 spTree 的 nvGrpSpPr 和 grpSpPr）
    for child in new_sp_tree:
        tag = etree.QName(child).localname
        if tag not in ('nvGrpSpPr', 'grpSpPr'):
            target_sp_tree.append(deepcopy(child))

    # 6. 处理 media 文件和 relationships
    slide_part = target_slide.part
    for filename, data in media_files.items():
        # 将图片数据写入 PPTX 的 media 目录
        image_part = slide_part.package.get_or_add_image_part(BytesIO(data))
        # relationship 已由 python-pptx 自动管理

    return target_slide
```

> 注意：`convert_svg_to_slide_shapes()` 中的 shape ID 是全局递增的，注入时需要确保不与模板中其他 slide 的 shape ID 冲突。可以通过偏移量调整所有 shape ID。

**Step 5：slide 顺序重排**

拆页会产生额外的 slide，需要维护一个"逻辑页码 → 实际 slide 列表"的映射：

```python
# 页码到 slide 索引的映射（一个页码可能对应多个 slide）
page_to_slides: dict[int, list[int]] = {}

# 重排 slide 顺序
sorted_pages = sorted(page_to_slides.keys())
new_order = []
for page_no in sorted_pages:
    new_order.extend(page_to_slides[page_no])

# 用 python-pptx 重排 slide
# presentation.slides._sldIdLst 支持直接操作顺序
sld_id_lst = presentation.slides._sldIdLst
for i, slide_idx in enumerate(new_order):
    sld_id = sld_id_lst[slide_idx]
    sld_id_lst.remove(sld_id)
    sld_id_lst.insert(i, sld_id)
```

### 5.4 新增 HybridPptxExporter

将整合逻辑封装为独立服务：

**目标位置**：`app/services/hybrid_pptx_exporter.py`

```python
class HybridPptxExporter:
    """混合导出器：将 SVG 页面和结构化页面整合到一个 PPTX"""

    def __init__(
        self,
        pptx_builder: PPTBuilder,           # 结构化填充引擎
        svg_to_pptx_adapter: SvgToPptxAdapter,  # SVG 转换适配器
    ) -> None:
        ...

    def export(
        self,
        template_pptx_path: Path,           # 模板 PPTX 路径
        template_rules: dict,               # 模板规则 JSON
        svg_pages: dict[int, Path],         # 页码 → SVG 文件路径
        structured_pages: dict[int, StructuredPageResult],  # 页码 → 结构化结果
        skipped_pages: set[int],            # 跳过的页码
        output_path: Path,                  # 输出 PPTX 路径
    ) -> Path:
        """
        整合流程：
        1. 用 python-pptx 打开模板 PPTX
        2. 结构化页面 → PPTBuilder._fill_slide() 回填
        3. SVG 页面 → convert_svg_to_slide_shapes() 注入
        4. 删除跳过的页面
        5. 重排 slide 顺序
        6. 保存
        """
        ...
```

### 5.5 编排服务导出阶段改造

当前 `orchestration_service.py` 的导出阶段：
```python
# 当前：所有页面都是 SVG，直接调用 svg_to_pptx
result_pptx_path = self.pptx_export_service.export(
    task_workspace.svg_final_dir,
    task_workspace.result_pptx_path
)
```

改造后：
```python
# 改造后：收集两种结果，调用混合导出器
svg_pages = {}           # 从 svg_final/ 收集
structured_pages = {}    # 从 structured_results/ 收集
skipped_pages = set()    # should_generate=false 的页面

result_pptx_path = self.hybrid_exporter.export(
    template_pptx_path=template_path,
    template_rules=template_rules_json,
    svg_pages=svg_pages,
    structured_pages=structured_pages,
    skipped_pages=skipped_pages,
    output_path=task_workspace.result_pptx_path,
)
```

### 5.6 整合方案的数据流图

```text
                    模板 PPTX
                       │
          ┌────────────┼────────────┐
          │            │            │
    TemplateRuleParser  │      python-pptx 打开
          │            │            │
    TemplateRules       │     Presentation 对象
          │            │            │
    ┌─────┴─────┐      │            │
    │           │      │            │
  SVG 页面   结构化页面  │            │
    │           │      │            │
  LLM 生成    LLM 生成  │            │
  SVG 文本    JSON 数据  │            │
    │           │      │            │
  svg_final/  structured_results/   │
    │           │                   │
    │     PPTBuilder._fill_slide() ──→ 回填到模板 slide
    │                               │
  convert_svg_to_slide_shapes()     │
    │                               │
  DrawingML XML ──→ 注入到模板 slide
    │                               │
    └─────────┬─────────────────────┘
              │
     重排 slide 顺序
              │
       保存最终 PPTX
```

## 6. 实现步骤

### 阶段一：移植核心模块（不改变现有流程）

1. **新建 `app/schemas/structured_generation.py`**：定义 `GeneratedElement`、`StructuredPageResult` 模型
2. **移植 `template_rule_parser.py`**：从 `pptx_gen/template/parser.py` 移植，适配数据模型
3. **移植 `pptx_builder.py`**：从 `pptx_gen/ppt/builder.py` 移植，去掉图片/Mermaid 逻辑，适配数据模型
4. **新建 `structured_prompt_builder.py`**：从 `pptx_gen/llm/prompts.py` 移植，去掉 Mermaid 部分

### 阶段二：LLM 客户端扩展

5. **在 `openai_like_client.py` 中新增 `generate_page_content` 方法**：调用 `_call_llm`，输出 `StructuredPageResult`
6. **在 `base.py` 的 `BasePageGenerationClient` 中新增抽象方法**

### 阶段三：编排服务融合

7. **新建 `pptx_builder_service.py`**：封装模板解析 + 结构化生成
8. **修改 `orchestration_service.py`**：在 `_process_one_page` 中按 `page_type` 分流，收集两种结果
9. **新建 `hybrid_pptx_exporter.py`**：实现整合导出逻辑
10. **修改 `orchestration_service.py` 导出阶段**：调用 `HybridPptxExporter` 替代 `PptxExportService`

### 阶段四：配置与依赖注入

11. **修改 `app/core/config.py`**：新增 `svg_page_types` 配置
12. **修改 `.env`**：新增 `SVG_PAGE_TYPES`
13. **修改 `app/services/bootstrap.py`**：注入 `PptxBuilderService` 和 `HybridPptxExporter`

### 阶段五：测试与文档

14. **补充测试**：模板解析、PPTBuilder 回填、结构化生成 prompt、SVG slide 注入
15. **更新文档**：readme.md、development_notes.md、architecture.md

## 7. 预期效果

| 指标 | 纯 SVG 方案 | 混合方案 |
|------|------------|----------|
| 15 页 PPT 生成时间 | 30-120 分钟 | 5-15 分钟（diagram 页少时） |
| 文本页编辑性 | 差（单行小文本框） | 好（原生文本框+表格） |
| 表格页编辑性 | 差（SVG 模拟表格） | 好（原生表格） |
| 图形页可编辑性 | 好（DrawingML 形状） | 好（仍用 SVG→DrawingML） |
| 封面/尾页编辑性 | 差（SVG 转换） | 好（原生文本框） |
| 自动拆页 | 不支持 | 支持（文本溢出自动分页） |
| LLM Token 消耗 | 高（每页输出完整 SVG） | 低（只有 diagram 页输出 SVG） |

## 8. 风险与注意事项

1. **模板兼容性**：`TemplateRuleParser` 依赖 PPTX 内部 XML 结构，不同模板可能有差异，需测试覆盖
2. **shape ID 冲突**：SVG 转换生成的 shape ID 可能与模板中已有的 shape ID 冲突，注入时需要做 ID 偏移
3. **拆页后页码映射**：结构化页面拆页后会产生额外 slide，需要维护原始页码到实际 slide 列表的映射
4. **relationship 管理**：SVG slide 注入时需要正确添加图片等媒体文件的 relationship，python-pptx 的 `part` API 可以辅助
5. **向后兼容**：已有任务如果全部走 SVG（`SVG_PAGE_TYPES=cover,toc,content,diagram,end`），不应受影响
6. **SVG 转换的 shape 数量**：`convert_svg_to_slide_shapes` 可能生成大量小 shape（特别是文字），diagram 页面仍可能存在编辑性问题，后续可考虑优化 SVG prompt 减少碎片段

## 9. 文件改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/schemas/structured_generation.py` | 新建 | 结构化生成数据模型 |
| `app/infrastructure/ppt_master/template_rule_parser.py` | 新建 | 从旧方案移植模板解析 |
| `app/infrastructure/ppt_master/pptx_builder.py` | 新建 | 从旧方案移植 PPT 构建（去掉图片逻辑） |
| `app/infrastructure/llm/structured_prompt_builder.py` | 新建 | 结构化生成 prompt |
| `app/infrastructure/llm/base.py` | 修改 | 新增 `generate_page_content` 抽象方法 |
| `app/infrastructure/llm/openai_like_client.py` | 修改 | 新增 `generate_page_content` 实现 |
| `app/services/pptx_builder_service.py` | 新建 | 结构化填充编排服务 |
| `app/services/hybrid_pptx_exporter.py` | 新建 | 混合导出器：整合 SVG slide + 结构化 slide |
| `app/services/orchestration_service.py` | 修改 | `_process_one_page` 按页面类型分流 + 导出阶段改用混合导出器 |
| `app/core/config.py` | 修改 | 新增 `svg_page_types` 配置 |
| `.env` | 修改 | 新增 `SVG_PAGE_TYPES` |
| `app/services/bootstrap.py` | 修改 | 注入 `PptxBuilderService` 和 `HybridPptxExporter` |
