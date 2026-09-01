# PPT 正文与单图 SVG 分离生成模式——现状分析与实施计划

> 文档版本：v4（最终确认版）
>
> 文档状态：方案已确认，等待代码实施
>
> 初始调研日期：2026-08-31；最终修订日期：2026-09-01
>
> 本阶段范围：仅分析和计划，不修改业务代码、数据库、接口或配置文件

## 1. 结论先行（v4）

### 1.1 是否需要重写全部接口

**不需要重写全部接口。** 现有任务查询、事件、产物、失败恢复、FTP、LLM 调用和结构化 PPT 能力均可复用。

最终确认后，采用一个很轻量的 `GenerationRequest`（生成输入）作为父级，而不是建设包含文件管理的复杂 GenerationProject：

- 一个 `generation_id` 保存一次输入文本、模板和全局执行参数；
- 正文任务和图形任务是两个可独立执行的平级任务；
- 图形任务下面可以产生多个 SVG 产物，产物数量不影响任务层级；
- 组装任务依赖正文和图形结果，是下游任务，不与二者平级；
- 只生成 SVG 时正文状态为 `not_requested`，不创建一个假的 pending 正文任务。

| 模块 | 复用程度 | v4 结论 |
|---|---:|---|
| API Key、统一响应、任务查询 | 高 | 直接复用 |
| TaskRunner、失败恢复、FTP/mock FTP | 高 | 复用并修复检查点续跑 |
| LLM 底层调用、并发、限流、重试 | 高 | 直接复用 `_call_llm` |
| 结构化文字生成和 PPTBuilder | 高 | 所有保留页统一使用 |
| 自动检查规则与 Prompt 注入 | 中高 | 继续复用，并叠加部署内置全局 JSON |
| 模板解析和图片识别 | 中 | 增加背景图、Logo、示意图和空白区识别 |
| 当前逐页编排 | 中 | 拆成正文、图形、组装三个任务类型 |
| 当前 SVG Prompt/整页注入 | 低到中 | 提取/转换复用，Prompt 和局部放置重做 |
| 纯文本输入 | 高 | 所有文档内容统一放入现有 `requirement_text` |
| SVG 预览/独立下载 | 低 | 新增直接返回安全 SVG 的接口 |

整体判断：**基础能力和大部分查询接口复用性高；新建一个输入父记录和少量接口，比把两个独立任务硬塞进单个 task 更清晰。**

### 1.2 两种模式共存

- `legacy_hybrid`：保留当前“普通页结构化、diagram 页整页 SVG”的旧模式；未显式传模式时继续使用旧模式。
- `separated_body_diagram`：新增模式：
  1. 多个文档解析后的纯文本统一进入 `requirement_text`，没有文档优先级；
  2. 只保留输入足以真实填写的模板页，信息不足就删除；
  3. 保留页全部使用结构化文字/表格，固定章节标题不变；
  4. 模板要求且信息充足的所有图形均生成，一图一个 SVG、每页最多一图；
  5. 正文和图形可分别触发，也可一起触发；
  6. 两者都完成后默认组装，图形部分失败时用成功图形继续组装并标记告警；
  7. 始终分别保留正文 PPT、每个 SVG 和组装 PPT。

## 2. 当前项目真实执行流程

### 2.1 接口到后台任务

当前主入口为 `POST /api/v1/tasks`：

1. `app/api/v1/endpoints/tasks.py:30-42` 接收 JSON 请求；
2. `app/services/task_service.py:35-93` 选择模板、保存 `request.json` 和 `requirement.md`、建立 FTP 路径、写任务表；
3. `app/infrastructure/tasking/runner.py:16-31` 启动后台任务；
4. `app/services/orchestration_service.py:74-299` 执行完整生成。

当前创建任务只接受：`requirement_text`、`template_id`、`custom_requirements`、`options`。它不是 multipart 接口，不能直接上传参考文件。

### 2.2 模板准备与规则解析

`run_task()` 当前会：

1. 加载模板 PPTX；
2. 复制模板逐页 SVG 和资源到任务工作区；
3. 从 `request_payload_json` 读取模型、思考模式、自定义要求；
4. 使用 `TemplateRuleParser` 解析模板文本框和表格；
5. 按模板 SVG 数量并发处理所有页。

模板规则只识别 `sp` 文本形状和 `graphicFrame` 表格，忽略图片、组合图形、图表、SmartArt 等图形占位对象。`_infer_page_purpose()` 实际只返回 `cover/table/text`，没有实现 schema 声明的 `toc/diagram/end` 完整分类。

### 2.3 单页规划与规则注入

每页在 `orchestration_service.py:360-388` 中执行：

1. 使用模板规则中的 `page_name/page_purpose/element_text` 匹配 `check_rules.json`；
2. 把匹配结果和任务级 `custom_requirements` 注入规划 Prompt；
3. LLM 返回 `should_generate/page_type/page_title`；
4. 根据 `should_generate` 决定保留或跳过页面。

这里存在两个不同的“页名”：

- 数据库中的 `page_name` 使用 SVG 文件名，如 `slide_15`；
- 规则匹配使用模板解析标题，如“项目整体架构图及说明”。

LLM 返回的 `page_title` 只存在于分析 JSON 中，没有落入分页表。

### 2.4 当前正文与 SVG 分流

`orchestration_service.py:430-459` 根据 `page_type` 和 `SVG_PAGE_TYPES` 做互斥分流：

- `diagram`：生成一整页 SVG；
- 其他类型：生成结构化 JSON，回填模板原生文本框和表格。

因此当前流程是“二选一”，不是“所有页生成文字 + 图形页额外生成单图”。

### 2.5 当前导出

`HybridPptxExporter` 以模板 PPTX 为底稿：

- 结构化页面：调用 `PPTBuilder.fill_single_slide()` 回填文字和表格；
- SVG 页面：调用 `_inject_svg_slide()`，先删除目标页几乎全部 shape，再注入整页 SVG 转换结果；
- 未提供结果的页面会被删除；
- 最终保存并上传 PPTX。

当前 SVG 注入是**整页替换**，会覆盖标题、正文、图片、表格和装饰，无法用于“只替换图形区域”。

## 3. 与本次需求直接相关的现存问题

### 3.1 生成与图形模型问题

1. 正文和 SVG 是互斥分支，无法同页同时保留原生文字和独立图形。
2. SVG Prompt 强制输出完整页面，和“一个图形一个 SVG”相反。
3. `PageGenerationResult` 只有 `generated_svg`，没有 `diagram_id/diagram_kind/section_title/description/placement`。
4. `svg_pages` 是固定模板 `page_no -> 整页 SVG`，无法表达独立图形、自动新增续页和组装后的最终页码。
5. `diagram_kind` 虽已存在于表和响应模型，但没有任何业务代码写入。
6. SVG 内嵌 metadata 只有页码、文件名和来源，没有真实页面标题、图形类型和图形说明。

### 3.2 模板与页码问题

1. 模板解析器没有完整提取图片、组合图形和其它元素的 bbox，系统无法可靠计算可替换示意图和空白区域。
2. 不能把“有图片”直接等同“需要生成架构图”；当前模板第 11、15、22、25、27、29、47、48 页均含图片，但用途不同。
3. 多个页面标题重复，例如多页“技术架构（续）”，仅靠标题不能形成稳定主键。
4. 页面可能被跳过或因正文溢出拆成多页，模板页码与最终 PPT 页码不一致。
5. 当前页码映射只在导出内存中存在，没有持久化，独立图形任务无法可靠定位最终输出页。
6. 模板无 title placeholder 时常回退为 `slide_N`，目录、封面、尾页识别不稳定。

### 3.3 规则匹配问题

1. 当前并不存在真正的向量检索/RAG 生成链路；实际能力是本地 `check_rules.json` 的关键词匹配。
2. 规则匹配发生在 LLM 规划之前，使用模板解析的 `page_purpose`；但解析器不产出 `diagram`，因此仅适用于 diagram 的规则可能漏匹配。
3. 当前任务级 `custom_requirements` 会注入所有页面，不能只指定标题关键词页。
4. 规则无优先级、强制覆盖、冲突提示和命中记录。
5. 未命中的用户新增参数会被 `SchemaModel(extra="ignore")` 静默丢弃，调用方容易误以为规则已生效。

### 3.4 纯文本输入问题

1. 已确认本服务不负责上传和解析文件，上游会把多个文档合并成一整段纯文本。
2. 各文档没有主次和优先级，也不需要在接口模型中拆成四类字段，统一放入现有 `requirement_text` 最简单。
3. `custom_requirements` 仍只放本次生成方式、措辞、特殊要求等指令，不应与事实材料混在一起。
4. 如果上游能保留 `【文档开始：名称】/【文档结束】` 这类简单边界，应保留，目的只是帮助识别冲突和来源，不表示优先级。
5. 若整段文本没有文档边界、日期和版本，服务无法可靠判断新旧，必须把所有内容平等提供给模型。
6. 内容冲突且无法确认时不得让模型猜测，应跳过冲突字段或相关页面。
7. 工作量估算文本由上游提供最终值，本服务不解析公式。
8. `requirement_text` 建议 5 万字开始告警、10 万字硬性拒绝；还需同时校验目标模型的上下文窗口。

### 3.5 预览与安全问题

1. 当前只返回 FTP 路径，没有浏览器可访问的鉴权预览 URL。
2. 现有 SVG 校验仅验证 XML 可解析且根节点是 `<svg>`，不能阻止 `script`、事件属性、`foreignObject`、外部资源等风险。
3. 直接内联展示 LLM 生成 SVG 可能造成前端 XSS 或外部请求。
4. 已确认直接预览 SVG，因此必须增加严格白名单净化、CSP 和安全响应头，不做 PNG 转换。

### 3.6 当前流程中应一并处理的可靠性问题

1. `max_page_concurrency` 和 `keep_artifacts` 在 schema 中存在，但业务代码未使用。
2. ThreadPool 使用总页数作为 worker 数，LLM 虽有全局信号量，DB/FTP/I/O 仍可能瞬间高并发。
3. 本期不要求新增停止能力；旧停止接口继续兼容，但不作为新模式验收重点。
4. 失败恢复是硬需求。当前恢复逻辑只识别带 `ftp_final_svg_path` 的已完成页；结构化页不能直接恢复，恢复后的 SVG 页也没有重新加入导出映射。
5. 新模式必须把正文页结果、单图结果和组装状态分别持久化，恢复时只重做失败/缺失步骤，不能覆盖已成功产物。
6. 模板规则解析失败时会回退到全页 SVG；新模式下这会直接违反“所有页文字生成”，应明确失败，禁止偷偷降级到整页 SVG。
7. 核心混合导出测试依赖本地固定任务数据，在 CI 中会跳过，无法保护本次局部插图改造。
8. 当前只有初始化 DDL，没有明确的增量数据库迁移机制。
9. FTP 产物已确认不设有效期，需要接受持续增长并提供容量监控，不能由服务自动清理。

## 4. 六项需求逐项复用评估（修订）

| 需求 | 已确认口径 | 复用判断 | 主要改造 |
|---|---|---|---|
| 1. 单独图形 SVG | 一个图形一个 SVG，每页最多一个，多个图形使用续页 | 中 | 新增单图 Prompt/模型/产物；自动寻找空闲区域或新增续页 |
| 2. 所有页走文字方案 | 只保留材料足以填写的页；保留页全部结构化填充，禁止编造 | 高 | 新模式取消正文的 SVG 分支；增加信息充分性判定和依据记录 |
| 3. 图形预览及说明 | SVG-only 显示图形/章节标题；组装后显示最终页码；各产物独立下载 | 中 | 新增图形实体、直接 SVG 预览/下载和组装页码回写 |
| 4. 正文与图形分开生成 | 两者独立触发；同一输入下自动关联和组装，保留三类产物 | 中高 | 增加轻量 generation_id；body/diagrams 平级，compose 为下游 |
| 5. 四类参考材料 | 上游合并为一整段纯文本，无主次优先级 | 很高 | 直接复用 `requirement_text`；只增加5万告警/10万上限配置 |
| 6. 标题关键词规范 | 部署内置全局 JSON，不属于任务输入，不强制保留页面 | 高 | 新增静态 JSON 和匹配器；任务 `custom_requirements` 最高优先级 |

### 4.1 页面保留与防编造规则

新模式必须把“页面是否适用”和“如何填写页面”分开：

1. 模板固定章节标题和章节结构不可变，不允许 LLM 生成或改写新的章节标题；
2. 先根据模板页面要求和全部输入材料判断信息是否充足；
3. 只有能从输入材料找到明确依据的页面才保留；
4. 只填写输入中存在的字段和内容，不允许用常识、示例、模板占位文案补全事实；
5. 信息不足、来源冲突且无法确认、仅有模板示例而没有项目事实时，删除该页；
6. 每个保留页记录用于判断和生成的 requirement_text 原文摘录，便于检查模型是否编造；
7. `page_type=diagram` 不再代表整页 SVG，只表示该章节可能额外需要独立图形。

### 4.2 单图和续页规则

1. 一个 SVG 只表示一个完整图形，不包含整页背景、固定标题、页脚和其它正文；
2. 每个最终 PPT 页面最多放一个图形；
3. 同一章节需要多个图形时，直接复制本章节版式形成续页；
4. 续页固定标题保持与被复制页面完全一致，不由模型另起标题；
5. SVG-only 清单只显示图形/章节标题；组装后再显示“章节标题 + 最终页码”，用户不需要手工选择 `page_key`；
6. 系统内部仍使用稳定 `page_key` 和 `diagram_id` 防止重复标题造成错位；
7. SVG metadata 至少包含 `diagram_id/task_id/page_key/template_page_no/final_page_no/section_title/diagram_kind/diagram_description/version`。

### 4.3 模板图片清理与图形放置

不要求修改模板 shape 名称或预先标记图形槽。新模式在正文导出前按确定性规则处理模板图片：

1. 图片宽度和高度均大于等于 PPT 版面宽高时，认定为背景图并保留；
2. 位于右上角的小型图片认定为企业 Logo 并保留；
3. 除背景图和右上角 Logo 外，其余模板图片全部删除；
4. 删除图片后，结合固定标题、已生成正文、表格、Logo 和装饰元素 bbox 计算可用空白区域；
5. 图形必须完整位于 PPT 版面内，且不能覆盖任何非空文字、表格、Logo 和必须保留的装饰；
6. 当前页能放下就等比放置，不能放下就复制本章节版式生成下一页；
7. 新增续页保持原标题完全不变，每页仍只放一个图形；
8. 输出图片清理清单、布局决策和碰撞检测结果，方便人工检查。

“AI 判断位置”只用于理解图形与章节关系；图片分类、遮挡检测和坐标放置必须由程序执行。右上角 Logo 默认识别条件为：图片左上角位于版面宽度 75% 之后、版面高度 20% 以内，且图片面积不超过版面 5%；三个阈值均做成服务配置项。

## 5. v4 目标任务关系与执行流程

### 5.1 一个输入 ID 关联多个执行任务

```text
GenerationRequest（generation_id，保存一次输入）
├─ requirement_text（多个文档合并后的事实全文）
├─ custom_requirements（本次生成指令）
├─ template_id / generation_mode / auto_compose
├─ planning_manifest（首次执行时生成，后续任务复用）
├─ BodyTask（0..1 个当前任务；未触发时为 not_requested）
│  └─ body.pptx + page_manifest.json
├─ DiagramTask（0..1 个当前任务；未触发时为 not_requested）
│  └─ DiagramResult[0..N]，每个结果一个 SVG
└─ ComposeTask（依赖 BodyTask 和 DiagramTask）
   └─ composed.pptx
```

正文和图形任务是平级的异步工作单元，因为两者都可以单独执行、失败和重试。图形任务产生多个 SVG 只是“一项任务有多个产物”，不影响其与正文任务平级。组装任务必须等待正文和至少一个可用图形，因此是下游依赖任务。

### 5.2 任务创建和自动关联

1. 创建 `GenerationRequest` 后得到稳定 `generation_id`；
2. 初次请求可指定 `targets=["body"]`、`["diagrams"]` 或 `["body","diagrams"]`；
3. 只请求图形时不创建正文 task，父记录显示 `body_status=not_requested`；
4. 以后可以在同一 `generation_id` 下补触发正文或图形任务；
5. 两类任务共享同一输入文本、模板和 planning manifest，不需要重复传全文；
6. 当同一 `generation_id` 下正文和图形均有可用结果且 `auto_compose=true` 时，自动创建或执行组装任务；
7. 图形部分失败时，成功图形照常组装，父记录标记 `completed_with_warnings`；
8. 失败子任务可继续执行，成功产物不覆盖、不重算。

### 5.3 共享规划阶段

首次执行正文或图形任务时生成并持久化规划清单：

1. 读取模板固定章节标题和页面填写要求；
2. 将整个 `requirement_text` 作为无优先级事实输入；
3. 对每页输出 `should_keep/information_sufficient/diagram_required/diagram_kind/reason`；
4. 不生成新的章节标题；
5. 规划结果、全局规则版本和 Prompt 配置形成快照，后触发的平级任务直接复用；
6. 如果输入文字或关键配置改变，应创建新的 `generation_id`，不能修改旧输入后继续混用结果。

### 5.4 正文任务

1. 只处理 `should_keep=true` 的页面；
2. 所有保留页走结构化文字/表格生成；
3. 只使用 `requirement_text` 中能明确找到依据的内容；
4. 按第 4.3 节保留背景图和右上角 Logo，删除其它模板图片；
5. 删除无关页面和模板填写说明；
6. 导出独立正文 PPTX 和最终页面映射；
7. 正文产物可单独下载。

### 5.5 图形任务

1. 不依赖正文任务即可执行；
2. 只为信息充足且模板要求图形的章节生成；
3. 图形类型不设白名单；
4. 每个图形独立保存、直接以 SVG 预览和下载；
5. SVG-only 场景不展示计划页码或最终页码，只展示图形标题/所属章节标题；
6. 图形 metadata 内部仍保存目标 `page_key`，供以后正文完成时自动组装。

### 5.6 组装任务

1. 以未组装正文 PPT 为底稿；
2. 只使用生成成功且校验通过的 SVG；
3. 删除正文阶段未清理干净的非背景、非 Logo 图片；
4. 在目标章节页寻找不遮挡文字且不超出版面的区域；
5. 放不下时复制本章节版式，保持原标题完全不变；
6. 部分图形失败不阻止成功图形组装，结果状态为 `completed_with_warnings`；
7. 组装后记录最终页码；
8. 正文 PPT、独立 SVG 和组装 PPT 使用不同 FTP 路径，全部长期保留。

## 6. 接口与任务层级方案（v4 推荐）

### 6.1 为什么增加 `generation_id`

只扩展单个 `/tasks` 无法优雅处理“先只生成 SVG，之后再生成正文并自动组装”。建议增加轻量父资源 `GenerationRequest`，只保存输入和关联关系，不包含文件上传、项目管理或在线规则维护。

创建一次输入后：

- 一个 `generation_id` 关联 `body_task_id`、`diagram_task_id` 和依赖性的 `compose_task_id`；
- body 与 diagrams 是平级任务；
- compose 是下游任务；
- task 下的产物数量可以不同，不影响任务层级；
- 同一 generation 后续补触发另一类任务时，无需重传 5万到10万字全文。

### 6.2 创建输入并触发任务

建议新模式使用：

```json
POST /api/v1/generations
{
  "generation_mode": "separated_body_diagram",
  "template_id": "tpl_xxx",
  "targets": ["body", "diagrams"],
  "auto_compose": true,
  "requirement_text": "上游合并后的全部文档纯文本",
  "custom_requirements": "本次任务额外要求，优先级最高",
  "options": {
    "output_filename": "方案.pptx",
    "model": "模型名称",
    "enable_thinking": false
  }
}
```

响应建议返回：

- `generation_id`；
- `body_task_id`，未请求时为 `null`；
- `diagram_task_id`，未请求时为 `null`；
- `compose_task_id`，依赖未满足时为 `null`；
- `body_status/diagram_status/compose_status`；
- `requirement_text_chars` 和是否超过5万字告警线。

后续补触发任务：

```json
POST /api/v1/generations/{generation_id}/tasks
{
  "task_type": "body"
}
```

也可填写 `diagrams`。如果同一 generation 下两类结果都已可用且 `auto_compose=true`，系统自动进入组装，不需要用户选择。

### 6.3 校验和默认值

- 新模式必须显式使用 `/generations` 或显式传 `generation_mode`；
- 原 `/tasks` 未传模式时继续执行 `legacy_hybrid`；
- `targets` 只允许 `body/diagrams`，至少一个；
- `auto_compose` 默认 `true`，只有两类结果都存在时才执行；
- `requirement_text` 超过配置的5万字告警线仍可执行；
- 超过10万字硬上限返回 422；
- 即使不超过10万字，也要校验所选模型上下文容量；
- `custom_requirements` 优先级最高，但不能覆盖防编造规则；
- 输入一旦已有子任务执行，不允许原地修改；修改输入需创建新 generation。

## 7. 推荐接口清单

### 7.1 现有接口继续复用

| 接口 | v4 处理方式 |
|---|---|
| `POST /api/v1/tasks` | 保持旧模式兼容；也作为内部/补充子任务创建模式参考 |
| `GET /api/v1/tasks` | 增加 `generation_id/task_type` 过滤和字段 |
| `GET /api/v1/tasks/{task_id}` | 返回子任务类型、状态、失败步骤和产物 |
| `GET /api/v1/tasks/{task_id}/pages` | 正文任务返回最终页面；图形任务不返回虚构页码 |
| `GET /api/v1/tasks/{task_id}/events` | 复用，增加正文、图形、组装、续页和恢复事件 |
| `GET /api/v1/tasks/{task_id}/artifacts` | 复用，增加正文 PPT、单图 SVG、清单和组装 PPT 类型 |
| `POST /api/v1/tasks/{task_id}/resume` | 失败子任务从检查点继续 |
| `GET /api/v1/tasks/{task_id}/download` | body 下载正文 PPT；compose 下载组装 PPT；旧任务下载旧结果 |
| `POST /api/v1/tasks/{task_id}/stop` | 保持兼容，不作为本期新模式验收重点 |

### 7.2 新增轻量输入与关联接口

| 接口 | 用途 |
|---|---|
| `POST /api/v1/generations` | 创建输入 ID，并按 targets 启动正文/图形任务 |
| `GET /api/v1/generations` | 查询当前 API Key 的 Generation 列表 |
| `GET /api/v1/generations/{generation_id}` | 聚合返回三个任务状态和全部下载入口 |
| `POST /api/v1/generations/{generation_id}/tasks` | 后续补触发 body 或 diagrams |
| `GET /api/v1/generations/{generation_id}/diagrams` | 汇总返回图形标题、章节、类型、状态和 URL |
| `GET /api/v1/tasks/{task_id}/diagrams/{diagram_id}` | 查询单图 metadata 和错误 |
| `GET /api/v1/tasks/{task_id}/diagrams/{diagram_id}/preview` | 直接返回净化后的 SVG，不转 PNG |
| `GET /api/v1/tasks/{task_id}/diagrams/{diagram_id}/download` | 独立下载最终 SVG |
| `GET /api/v1/tasks/{task_id}/artifacts/{artifact_id}/download` | 精确下载正文或组装 PPT、manifest 等产物 |

### 7.3 明确不新增

- 不新增文档上传、OCR、PDF/DOCX/XLSX 解析接口；
- 不新增复杂 GenerationProject；
- 不新增任务级页面规范管理接口；
- 不要求用户选择重复标题、图形位置或组装版本。

## 8. `requirement_text` 与响应设计（v4）

### 8.1 是否需要区分原需求和新增文档

按当前实践，多个文档之间没有优先级，也没有“以原需求为主”的规则，因此**不需要增加四类材料字段，可以全部放入现有 `requirement_text`**。

这样做的优点：

- 不修改事实输入的核心接口语义；
- 所有页面天然获得同一份完整上下文；
- 不需要文档分类、版本选择和材料数据表；
- 上游只负责把解析结果合并为纯文本。

代价：后端不能可靠区分每段来自哪个文档，也不能自动判断哪个版本更新。如果未来需要精确溯源，再增加结构化材料数组，不在本期提前设计。

### 8.2 已确认的文档边界格式

上游合并文本会包含文档标题，并使用很长的半角横线分隔，例如：

```text
需求文档
----------------------------------------
……纯文本……

工作量估算书
----------------------------------------
……最终值纯文本……
```

服务不需要把这些内容重新解析成结构化字段，但构建 Prompt 时应明确告诉模型：“标题和连续横线表示新文档开始，各文档地位相同”。建议增加 `DOCUMENT_SEPARATOR_MIN_HYPHENS=20` 配置；去除首尾空格后，连续至少 20 个 `-` 的单独一行视为边界。边界只帮助理解和发现冲突，不产生优先级。

### 8.3 长度配置

建议新增服务配置：

- `REQUIREMENT_TEXT_WARN_CHARS=50000`：达到后记录告警并在创建响应中返回 warning；
- `REQUIREMENT_TEXT_MAX_CHARS=100000`：超过后返回 422，不创建 generation；
- 校验单位为 Unicode 字符数，不按文件字节数；
- 字符数合格后仍需根据所选模型检查上下文 token 上限；
- 禁止静默截断，否则可能错误删除页面或生成不完整图形。

### 8.4 输入冲突和防编造

- 所有文档内容平级；
- 有明确文字说明新旧关系时，模型可以依照原文；
- 没有明确新旧关系时不能自行决定哪个版本正确；
- 冲突影响核心内容时跳过相关字段或页面；
- 每页分析结果保存用于判断的原文摘录，而不是不存在的 `material_id`；
- `custom_requirements` 优先级最高，但“不能生成输入中没有的事实”是不可覆盖的硬规则。

### 8.5 聚合响应

`GET /generations/{generation_id}` 建议返回：

- `generation_id/generation_mode/auto_compose`；
- `requirement_text_chars/requirement_text_warning`；
- `body_task_id/diagram_task_id/compose_task_id`；
- `body_status/diagram_status/compose_status`；
- `kept_page_count/skipped_page_count/diagram_count`；
- `body_pptx_artifact_id/composed_pptx_artifact_id`；
- `has_body_download/has_diagram_downloads/has_composed_download`；
- `status=completed/completed_with_warnings/failed/running`；
- 失败步骤摘要和继续执行入口。

图形清单至少返回：

- `diagram_id/status/version`；
- `diagram_title/section_title/diagram_kind/diagram_description`；
- SVG-only 时不返回页码；组装后可返回 `final_page_no`；
- `preview_url/download_url`；
- `evidence_quotes/applied_check_rule_ids/applied_global_rule_ids`；
- `layout_decision/validation_status/error_message`。

## 9. 全局页面生成规范 JSON 设计

### 9.1 定位

该规范是服务部署自带的全局配置，不由创建任务接口传入，也不建立管理接口。建议目标路径：

`app/config/page_generation_rules.json`

它只负责“命中固定模板章节标题后追加哪些生成要求”，不强制页面生成。页面仍必须通过信息充分性判断。

### 9.2 建议 JSON 结构

```json
{
  "schema_version": "1.0",
  "rules": [
    {
      "id": "global_page_rule_001",
      "enabled": true,
      "description": "由维护人员填写规则用途，不注入模型",
      "template_scope": ["*"],
      "title_match": {
        "mode": "any_contains",
        "keywords": ["待填写标题关键词1", "待填写标题关键词2"],
        "normalize_whitespace": true,
        "ignore_suffixes": ["（续）", "(续)"]
      },
      "apply_to": ["planning", "body", "diagram"],
      "instruction": "请在这里填写命中页面后必须遵守的生成规范。",
      "priority": 100
    }
  ]
}
```

字段说明：

- `schema_version`：配置格式版本；
- `id`：全局唯一且稳定，用于日志和结果追溯；
- `enabled`：是否生效；
- `description`：给维护人员看的说明，不进入 Prompt；
- `template_scope`：`["*"]` 表示所有模板，也可填写具体模板 ID；
- `title_match.mode`：第一版支持 `any_contains/all_contains/equals`；
- `title_match.keywords`：只匹配模板固定章节标题，不匹配 LLM 生成标题；
- `ignore_suffixes`：允许“标题”和“标题（续）”共享规则；
- `apply_to`：控制规划、正文、图形哪些阶段注入；
- `instruction`：用户后续需要填写的实际规范；
- `priority`：多个全局规则命中同页时的排序依据。

第一版不支持正则表达式，也不提供 `force_generate`，防止全局规范破坏“信息不足就删页”的原则。

### 9.3 匹配和优先级

1. 只对模板固定章节标题做确定性匹配；
2. 模板固定章节标题禁止被 LLM 改写；
3. 相同 `id` 去重；
4. 多条全局规范同时命中时按 `priority` 升序拼接，全部生效；
5. 冲突时优先级由低到高为：模板要求 → 自动 `check_rules.json` → 全局页面生成规范 → 当前任务 `custom_requirements`；
6. `custom_requirements` 永远最高，但不能指示模型编造输入中不存在的事实；
7. 命中的全局规则 ID 必须写入页面和图形分析结果；
8. 配置缺字段、重复 ID、空关键词、空 instruction 时启动告警；严重格式错误时新模式禁用，不能静默跳过。

### 9.4 与现有自动规则的边界

- `check_rules.json`：现有合规与内容检查要求；
- `page_generation_rules.json`：部署内置、按模板固定章节标题命中的正向生成规范；
- `custom_requirements`：当前任务临时设置，最高优先级；
- 三者分别展示和记录，避免无法追溯最终 Prompt 来源。

## 10. 已确认不纳入本期的能力

- 不上传或解析 DOCX、XLSX、PDF、PPTX 等原始文件；
- 不接入外部知识库、向量检索或 RAG；
- 不建设 GenerationProject 和参考文件管理；
- 不提供全局页面规范的在线维护接口，由部署配置 JSON；
- 不要求用户手工选择重复标题、图形槽位或组装版本；
- 不新增停止任务能力，旧接口仅保持兼容；
- 不为 FTP 产物设置自动过期和删除策略；
- 不在本次计划中实现前端人工微调编辑器。

## 11. 数据库修改范围（v4）

### 11.1 新增 `sg_generation_request`

该表是轻量输入父记录，不是项目管理表。主要字段方向：

- `generation_id/api_key/template_id/generation_mode`；
- `requirement_text/custom_requirements/request_payload_json`；
- `auto_compose/status/warning_message`；
- `requirement_text_chars/planning_manifest_ftp_path`；
- `body_task_id/diagram_task_id/compose_task_id`；
- `body_status/diagram_status/compose_status`；
- `created_at/updated_at/completed_at`。

输入一旦有子任务开始执行即冻结。后续补触发任务只引用 `generation_id`。

### 11.2 新增 `sg_generation_diagram`

一行保存一个独立图形：

- `diagram_id/generation_id/task_id/page_key/template_page_no/final_page_no`；
- `diagram_title/section_title/diagram_kind/diagram_description/version/status`；
- `ftp_original_svg_path/ftp_final_svg_path`；
- `evidence_quotes_json/applied_rule_ids_json`；
- `layout_decision_json/validation_status/error_message`；
- `created_at/updated_at/completed_at`。

SVG-only 时 `final_page_no` 为空；组装完成后回写。

### 11.3 扩展现有表

1. `sg_generation_task`
   - 增加 `generation_id/task_type`，其中类型为 `body/diagrams/compose/legacy`；
   - 可增加 `depends_on_task_ids_json` 供 compose 记录依赖；
   - 为兼容现有 NOT NULL 字段，子任务可复制父记录的 `requirement_text`，但父记录是逻辑事实源。
2. `sg_generation_task_page`
   - 增加 `page_key/template_page_title/information_sufficient/evidence_quotes_json`；
   - 增加 `diagram_required/page_type/final_page_no`；
   - 新模式不保存模型生成章节标题。
3. `sg_generation_task_artifact`
   - 表结构复用；新增 `body_pptx/diagram_svg/diagram_manifest/page_manifest/composed_pptx` 类型。

不新增 reference file、page spec 或复杂 project 表。全局页面规范仍使用静态 JSON。

### 11.4 迁移与保留

- 使用独立增量迁移脚本，不只修改初始化 DDL；
- 老任务新增字段允许为空；
- 索引覆盖 `generation_id`、`generation_id + task_type`、`task_id + status`、`task_id + diagram_id`；
- 所有产物只存 FTP，不自动过期；
- 记录 FTP 容量和上传失败，不在本期提供删除接口。

## 12. 代码修改范围（v4）

### 12.1 API、Schema 和持久化

| 文件/模块 | 修改方向 |
|---|---|
| 新增 generation schema | 创建输入、聚合状态、补触发子任务请求/响应 |
| `app/schemas/task.py` | 增加 generation_id、task_type 和子任务摘要；旧请求保持兼容 |
| 新增 diagram schema | 定义单图 metadata、列表和详情 |
| 新增 generations 端点 | 创建父输入、聚合查询、补触发 body/diagrams |
| `app/api/v1/endpoints/tasks.py` | 扩展任务查询、恢复和精确产物下载 |
| 新增 diagrams 端点 | 直接 SVG 预览与下载 |
| `app/api/v1/router.py` | 注册 generations 和 diagrams 路由 |
| 新增 generation repository | 管理输入父记录和子任务关联 |
| `task_repository.py` | 增加 generation/task type、分页字段和 diagram CRUD |

### 12.2 服务与编排

| 文件/模块 | 修改方向 |
|---|---|
| 新增 generation service | 冻结输入、创建子任务、聚合状态、满足依赖时自动组装 |
| `task_service.py` | 支持 child task 类型、失败续跑和精确产物下载 |
| `orchestration_service.py` | 保留旧流程；新任务按 body/diagrams/compose 分发 |
| 新增/拆分 body generation service | 结构化填充、图片清理、正文 PPT 和 page manifest |
| 新增 diagram generation service | 一图一 SVG、章节/type/依据和持久化 |
| 新增 composition service | 版面内无文字遮挡放置、自动续页、部分成功组装 |
| 新增 global page rule matcher | 加载静态 JSON 并按固定章节标题注入 |

### 12.3 LLM 与 Prompt

| 文件/模块 | 修改方向 |
|---|---|
| `app/infrastructure/llm/base.py` | 新增信息充分性规划和 DiagramResult 契约 |
| `openai_like_client.py` | 复用 `_call_llm`，新增单图 SVG 生成 |
| `prompt_builder.py` | 新增单图 Prompt，禁止整页 SVG 和输入外事实 |
| `structured_prompt_builder.py` | 直接传完整 requirement_text、全局规则和证据要求 |
| `rule_matcher.py` | 修复模板 page purpose，继续处理现有 check rules |

### 12.4 模板、PPT、SVG 和配置

| 文件/模块 | 修改方向 |
|---|---|
| `structured_generation.py` | 增加 page key、充分性、证据摘录和图形需求 |
| `template_rule_parser.py` | 提取真实章节标题及全部元素 bbox |
| 新增模板图片分类器 | 保留整页背景和右上角小 Logo，删除其它图片 |
| `pptx_builder.py` | 原生文字/表格回填，固定章节标题，输出页码映射 |
| `hybrid_pptx_exporter.py` | 旧模式保留；新模式不清空整页 |
| 新增 diagram composer/injector | 图形不超版面、不覆盖文字；放不下复制续页 |
| `project_workspace.py` | 增加 generation manifests、diagram、body/composed exports 目录 |
| `core/constants.py` | 增加 generation、正文、单图、manifest、组装产物类型 |
| `core/config.py` | 增加5万字告警、10万字上限、Logo识别阈值、SVG安全和并发配置 |
| `bootstrap.py` / `container.py` | 注入新增 repository、matcher、生成和组装服务 |
| SQL | 新增两张表、扩展现有表并提供增量迁移 |

### 12.5 测试与文档

- generation 与 body/diagrams/compose 层级和依赖测试；
- 先 diagrams 后 body 自动组装、只生成 SVG 时 body=not_requested 测试；
- requirement_text 5万告警、10万拒绝和模型上下文不足测试；
- 无文档优先级、冲突不猜测、防编造不可覆盖测试；
- 背景图保留、右上角 Logo 保留、其它图片删除测试；
- 固定章节标题、无依据页删除、证据摘录测试；
- 全局 JSON 匹配和 custom 最高业务优先级测试；
- 一页一图、多图续页、版面边界和文字碰撞测试；
- 直接 SVG 预览的脚本、事件、外链净化测试；
- 部分图形失败仍组装并返回 completed_with_warnings 测试；
- 三类产物独立 FTP 路径和下载测试；
- 子任务失败续跑且成功步骤不重复测试；
- 旧 `legacy_hybrid` 回归测试；
- 更新根 README、API、架构和数据库文档。

## 13. 分阶段实施计划（v4）

### 阶段 0：固定输入和版式样本

1. 固定包含“文档标题 + 长横线边界”的合并纯文本样例；
2. 固定背景图、右上角 Logo、普通图片三类模板页样本；
3. 准备仅正文、仅图形、先图形后正文、部分图形失败、多图续页验收场景；
4. 填写第 9 节全局规则 JSON 的真实关键词和规范；
5. 将本 v4 文档作为实施基线，后续变更需同步 API 与架构文档。

### 阶段 1：父输入、子任务和数据库迁移

1. 新增 GenerationRequest schema、表、repository 和 service；
2. `sg_generation_task` 增加 generation_id 和 task_type；
3. 新增 diagram 表和任务/分页字段；
4. 定义正文、SVG、manifest、组装 PPT 产物类型；
5. 创建输入后按 targets 创建 body/diagrams 子任务；
6. 支持同一 generation 后续补触发另一类任务。

### 阶段 2：配置与全局页面规范

1. 增加5万字告警、10万字硬上限和模型上下文校验；
2. 增加背景图、右上角 Logo 判断阈值配置；
3. 按第 9 节增加静态页面规范 JSON；
4. 启动时校验 JSON 格式、关键词和重复 ID；
5. 固化防编造不可覆盖、custom requirements 业务优先级最高的顺序。

### 阶段 3：共享规划清单

1. 直接使用完整 `requirement_text`，不再拆分四类材料字段；
2. 固定模板章节标题，识别动态标题占位；
3. 对每页判断信息充分性、是否保留、是否需要图形和图形类型；
4. 保存判断依据的原文摘录；
5. 固化 planning manifest 和全局规则版本；
6. body 与 diagrams 任务复用同一份规划结果。

### 阶段 4：正文任务和图片清理

1. 所有保留页只走结构化文字/表格；
2. 封面项目名和其它动态标题按输入替换，章节名不变；
3. 宽高均覆盖版面的图片作为背景保留；
4. 右上角小型图片作为企业 Logo 保留；
5. 其它模板图片全部删除；
6. 导出可独立下载的正文 PPT 和 page manifest。

### 阶段 5：图形任务

1. 新增 DiagramPlan/DiagramResult 和单图 Prompt；
2. 所有模板要求的图形类型均可生成；
3. 只在输入信息充分时生成；
4. 每个图形独立保存 SVG 和 metadata；
5. SVG-only 不展示页码，只展示图形标题和章节标题；
6. 增加 SVG 结构、安全、边界和 DrawingML 兼容校验。

### 阶段 6：直接 SVG 预览和下载

1. 新增图形列表、详情、预览和下载接口；
2. 预览直接返回净化后的 `image/svg+xml`，不生成 PNG；
3. 删除脚本、事件属性、外部 URL、foreignObject 等危险内容；
4. 下载最终净化 SVG，原始模型输出仅作为内部诊断产物；
5. 图形列表不为 SVG-only 结果制造虚假页码。

### 阶段 7：自动布局与部分成功组装

1. 以正文 PPT 为底稿；
2. 计算文字、表格、背景和 Logo 占用区域；
3. 图形必须在版面内且不覆盖文字；
4. 当前页放不下时复制本章节版式并保持原标题；
5. 成功图形照常组装，失败图形记录告警；
6. 输出状态为 completed_with_warnings 并允许失败图形继续执行；
7. 同时保留正文 PPT、单图 SVG 和组装 PPT。

### 阶段 8：自动依赖、失败续跑和兼容

1. 同一 generation 下两类结果可用时自动触发 compose；
2. 先 diagrams 后 body 与先 body 后 diagrams 行为一致；
3. 恢复时只重做失败图形、正文页或组装步骤；
4. 成功结果从 FTP 恢复，不重复调用模型；
5. 未显式使用新模式的旧 `/tasks` 调用保持原行为；
6. FTP 不设过期，但增加容量和上传失败监控；
7. 更新 API、数据库、全局 JSON、架构和故障恢复文档。

## 14. 最终方案变化汇总

| 早期方案 | v4 最终决定 |
|---|---|
| 单个 task 通过 scope 产生多类结果 | 增加 generation_id，正文和图形为平级子任务，组装为下游任务 |
| 四类材料使用 reference_materials 数组 | 所有文档平级合并，直接复用 requirement_text |
| 依赖版本字段选择最新材料 | 不再做后端版本排序；无明确原文依据时不判断新旧 |
| 5万/10万只是待确认 | 确认为5万字告警、10万字硬上限，并校验模型上下文 |
| 模板图片按示意图识别 | 明确保留整页背景和右上角 Logo，其它图片全部删除 |
| 部分图形失败策略待定 | 确认成功图形继续组装，状态 completed_with_warnings |
| SVG-only 展示规划页码 | 不展示任何页码，只展示图形标题/章节标题 |
| 优先使用已有续页 | 需要续页时直接复制本章节版式并保持原标题 |
| PNG 预览优先 | 直接预览净化后的 SVG，不做后台图片转换 |
| 动态标题待确认 | 封面项目名按输入填写；其它明显动态占位也按同一原则处理 |
| Logo 阈值待确认 | 阈值配置化，默认右侧75%后、顶部20%内、面积不超过5% |
| 文档边界格式待确认 | 使用“标题 + 至少20个连续半角横线”识别边界，不产生优先级 |
| 任务层级待确认 | 正式采用 GenerationRequest → BodyTask/DiagramTask → ComposeTask |

## 15. 已确认的产品决策（v4）

### 15.1 内容和标题

1. 只保留 requirement_text 中信息足以真实填写的页面。
2. 防编造是不可覆盖的硬规则。
3. 所有保留页走结构化文字/表格方案。
4. 固定章节名不变，不允许模型创建新章节标题。
5. 封面项目名称根据输入填写；“系统1”等明显动态占位按输入替换。
6. 所有模板要求且信息充足的图形都生成，不限制类型。
7. 每页最多一个图；多个图形复制本章节版式形成续页，原标题不变。

### 15.2 模板图片和布局

8. 图片宽高均大于等于 PPT 版面时视为背景并保留。
9. 右上角小型图片视为企业 Logo 并保留；默认阈值为左上角在宽度75%后、高度20%内、面积不超过5%，且全部可配置。
10. 其它所有模板图片均删除。
11. 图形不得覆盖文字、表格和 Logo，也不得超出 PPT 版面。
12. 当前页放不下就复制本章节版式到下一页。
13. 最终人工仍可检查和微调版式。

### 15.3 输入文本

14. 服务不接收或解析文件，上游提供合并纯文本。
15. 各文档没有优先级或主次，统一放入 requirement_text。
16. custom_requirements 只放任务指令，业务优先级最高但不能要求编造事实。
17. 工作量只使用上游解析出的最终值。
18. requirement_text 达到5万字告警，超过10万字拒绝。
19. 每页都携带完整 requirement_text，不做检索或按文档分类。
20. 文档边界采用“标题 + 很长的连续半角横线”；默认至少20个 `-`，仅用于帮助模型分段，不产生优先级。

### 15.4 任务和产物

21. 一个 generation_id 关联正文、图形和组装任务。
22. 正文与图形是平级任务，可分别单独执行。
23. 图形任务可以产生多个 SVG 产物，不影响其任务层级。
24. 组装任务依赖正文和图形，是下游任务。
25. 只生成 SVG 时正文状态为 not_requested，不创建假任务。
26. 同一 generation 后续补齐另一任务后，auto_compose=true 时自动组装。
27. 部分图形失败时成功图形继续组装，并标记 completed_with_warnings。
28. 正文 PPT、独立 SVG、组装 PPT 均单独保留和下载。
29. SVG-only 不显示页码，只显示图形标题或章节标题。
30. 失败子任务可以继续，已成功步骤不重复生成。

### 15.5 规则、预览和运维

31. 页面规范由部署内置 JSON 提供，只匹配固定章节标题。
32. 全局规范不强制保留信息不足的页面。
33. SVG 直接预览，不进行 PNG 转换，但必须先安全净化。
34. 新模式需显式使用；未传模式的旧 `/tasks` 调用保持旧行为。
35. 本期不新增停止能力。
36. FTP 产物不设有效期。
37. 现有接口允许增加响应字段。

## 16. 确认状态

所有产品和架构问题均已确认，当前没有阻塞实施的问题：

1. Logo 识别阈值采用配置项，默认宽度位置 75%、高度位置 20%、面积 5%；
2. 上游使用“文档标题 + 很长的连续半角横线”表示文档边界，默认至少 20 个 `-`；
3. 正式采用 GenerationRequest → BodyTask/DiagramTask → ComposeTask 层级；
4. 本 v4 文档是后续接口、数据库和代码实现的统一设计基线。

## 17. 验收标准（v4）

### 17.1 功能验收

1. 创建新模式输入后返回 generation_id 和实际创建的子任务 ID。
2. 只请求 diagrams 时 body_status=not_requested，不创建正文任务。
3. 后续在同一 generation 下触发 body 后自动满足组装依赖。
4. 新模式只保留有明确输入依据的页面，无依据页面删除。
5. 固定章节名不变，封面项目名和动态占位按输入填写。
6. body 任务不产生整页 LLM SVG，保留页均为结构化结果。
7. diagrams 任务不依赖正文，每个图形生成一个独立 SVG。
8. SVG-only 图形列表不显示页码，只显示图形标题、章节、类型和说明。
9. 每个最终页最多一个图；放不下时复制章节版式且原标题不变。
10. 背景图和右上角 Logo 保留，其它模板图片删除。
11. 图形完整位于 PPT 版面内，不覆盖文字、表格和 Logo。
12. 部分图形失败时成功图形仍组装，并返回 completed_with_warnings。
13. 正文 PPT、每个 SVG、组装 PPT 均有独立 FTP 产物和下载入口。
14. requirement_text 达5万字产生告警，超过10万字返回422。
15. 全局 JSON 只命中固定章节标题，custom requirements 业务优先级最高。
16. 失败任务只重做失败或缺失步骤，不覆盖成功结果。
17. 旧模式 API 和已有数据不受影响。

### 17.2 质量与安全验收

1. 页面和图形保存用于判断的 requirement_text 原文摘录，抽检不得出现输入外业务事实。
2. 输入冲突、信息不足、模型上下文不足时明确报告，不静默截断或猜测。
3. SVG 预览前删除脚本、事件属性、外部 URL、foreignObject 等危险内容。
4. SVG 超界、元素过多或无法转 DrawingML 时该图失败，不损坏其它产物。
5. 图片分类和图形放置均由确定性规则执行，不仅依赖模型判断。
6. 正文、SVG 和组装 PPT 使用不同 FTP 路径，组装不覆盖源产物。
7. 服务重启和失败恢复不会丢失成功结果，也不会重复调用成功步骤。
8. 核心流程使用固定 CI 夹具，不依赖本机历史任务目录。
9. FTP 产物不自动过期，并提供容量和上传失败监控。

## 18. 本阶段不实施内容

本轮只同步设计文档，不修改业务代码、依赖、数据库、接口、模板或全局 JSON 文件。方案已确认，后续可以直接按本文档进入代码实施。
