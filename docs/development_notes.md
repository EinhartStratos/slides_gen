# slides_gen_server 开发说明

> 文档版本：v4，更新日期：2026-09-01
>
> **状态说明**：当前代码仍实现 `legacy_hybrid`；正文与单图 SVG 分离模式已经完成设计、尚待代码实现。待实现内容以粗体“【待实现】”标记。

## 1. 项目结构

```text
app/
├─ api/v1/endpoints/        接口层（health, tasks, templates）
├─ config/                  配置文件
│  └─ check_rules.json      内容检查规则（66 条，用于规则注入）
├─ core/                    配置(config.py)、常量(constants.py)、异常(exceptions.py)
├─ schemas/                 Pydantic 数据模型
│  ├─ task.py               任务请求/响应模型（含 custom_requirements）
│  ├─ template.py           模板模型
│  ├─ common.py             通用响应模型
│  └─ structured_generation.py  结构化生成结果模型
├─ services/                业务编排层
│  ├─ orchestration_service.py    任务全生命周期编排（含规则匹配与注入）
│  ├─ slide_generation_service.py  逐页规划与 SVG 生成
│  ├─ pptx_builder_service.py      结构化内容生成（LLM → JSON → 回填模板）
│  ├─ hybrid_pptx_exporter.py      混合导出（结构化 + SVG → PPTX）
│  ├─ task_service.py             任务 CRUD 和状态管理
│  ├─ template_service.py         模板查询与复制
│  ├─ template_import_service.py  模板导入（PPTX→SVG）
│  ├─ builtin_template_service.py 公共模板管理
│  ├─ svg_validation_service.py   SVG 校验
│  ├─ pptx_export_service.py      SVG→PPTX 导出
│  └─ bootstrap.py                服务依赖组装（含 RuleMatcher 注入）
├─ infrastructure/
│  ├─ db/                   MySQL 数据库适配
│  │  └─ task_repository.py 任务/页面/事件/产物 CRUD
│  ├─ storage/ftp.py        FTP/mock_ftp 存储适配
│  ├─ llm/                  LLM 客户端
│  │  ├─ base.py            抽象接口 + Pydantic 模型
│  │  ├─ openai_like_client.py  OpenAI 风格 API 客户端（httpx2）
│  │  ├─ concurrency.py     全局信号量管理
│  │  ├─ prompt_builder.py  规划和 SVG 生成 prompt 构建器
│  │  ├─ structured_prompt_builder.py  结构化内容生成 prompt 构建器
│  │  └─ rule_matcher.py    检查规则匹配器（按页面匹配 check_rules.json）
│  └─ ppt_master/           PPTX↔SVG 转换引擎
│     ├─ project_workspace.py
│     ├─ pptx_to_svg_adapter.py
│     └─ svg_to_pptx_adapter.py
├─ vendor/ppt_master/       内置运行时脚本和模板资源
│  ├─ scripts/pptx_to_svg/
│  ├─ scripts/svg_to_pptx/
│  ├─ scripts/svg_finalize/
│  └─ templates/icons/      SVG 图标资源（embed_icons.py 引用）
└─ main.py
```

新模式实现后将增加：

```text
app/
├─ api/v1/endpoints/
│  ├─ generations.py                 # 【待实现】输入父记录与任务关联
│  └─ diagrams.py                    # 【待实现】SVG详情、预览、下载
├─ schemas/
│  ├─ generation.py                  # 【待实现】generation请求/聚合响应
│  └─ diagram.py                     # 【待实现】图形模型
├─ infrastructure/db/
│  ├─ generation_repository.py       # 【待实现】sg_generation_request
│  └─ diagram_repository.py          # 【待实现】sg_generation_diagram
├─ services/
│  ├─ generation_service.py          # 【待实现】子任务关联与自动组装
│  ├─ body_generation_service.py     # 【待实现】结构化正文与图片清理
│  ├─ diagram_generation_service.py  # 【待实现】一图一个SVG
│  └─ composition_service.py         # 【待实现】局部插图与续页
└─ config/
   └─ page_generation_rules.json     # 【已落地】全局标题关键词生成规范
```

## 2. 核心生成链路

### 2.1 当前旧模式：SVG + 结构化填充【已实现】

系统支持两种生成方式，按页面类型自动分流：

- **SVG 生成**（`diagram` 类型页面）：LLM 生成完整 SVG → 转为可编辑 DrawingML 形状
  - 适用于架构图、流程图、时序图等复杂图形页
  - 由 `slide_generation_service.py` + `prompt_builder.py` 驱动
- **结构化填充**（`cover/toc/content/end` 类型页面）：LLM 输出结构化 JSON → 回填模板原生文本框和表格
  - 速度快、编辑性好、支持自动拆页
  - 由 `pptx_builder_service.py` + `structured_prompt_builder.py` 驱动

页面类型分流由环境变量 `SVG_PAGE_TYPES` 控制（默认 `diagram`）。

### 2.2 两阶段逐页生成

每个页面独立走两个阶段：

**阶段一：规划（plan_single_page）**
- 输入：需求文本 + 当前页模板 SVG + 匹配的检查规则 + 自定义要求
- LLM 返回 JSON：`should_generate`、`skip_reason`、`page_type`、`page_title`
- 规则：封面/尾页/目录页始终 `should_generate=true`
- 失败处理：重试 3 次，仍失败则回退启发式逻辑

**阶段二：生成**
- SVG 路径：`generate_page_svg` → LLM 直接输出完整 SVG 代码
- 结构化路径：`generate_page_content` → LLM 输出结构化 JSON（文本/表格）
- 失败处理：重试 3 次，仍失败则标记 `decision_source=failed`，该页不输出到最终 PPTX

### 2.3 任务编排流程

```
run_task()
├─ 加载模板，复制 SVG 到任务工作区
├─ 解析 request_payload_json 获取 options.model / options.enable_thinking / custom_requirements
├─ 解析模板规则（template_rules.json）
├─ ThreadPoolExecutor 并发提交所有页面
│  └─ _process_one_page(page_no)
│     ├─ RuleMatcher 匹配该页检查规则
│     ├─ 规划（plan_single_page）→ LLM 返回 JSON
│     ├─ should_generate=false → 跳过，记录 skip_reason
│     ├─ 按 page_type 分流：
│     │  ├─ SVG 路径 → generate_page_svg → LLM 返回 SVG
│     │  └─ 结构化路径 → _process_structured_page → generate_page_content → LLM 返回 JSON
│     └─ 正常生成 → 写入 svg_output / svg_final / structured_results
├─ 全局信号量控制 LLM 请求总并发（MAX_LLM_CONCURRENCY）
├─ 429 限流退避：Retry-After 优先，无则指数退避+抖动
├─ 网络错误退避重试
├─ 线程锁保护进度计数器
├─ 混合导出 PPTX
│  ├─ 结构化页面 → PPTBuilder 回填原生文本框/表格
│  ├─ SVG 页面 → convert_svg_to_slide_shapes 注入 DrawingML 可编辑形状
│  ├─ 删除跳过的页面 → 重排 slide 顺序
│  └─ 保存最终 PPTX
├─ 上传产物到 FTP
└─ finally: 清理 runtime 任务目录
```

### 2.4 分离生成模式【待实现】

```text
GenerationRequest (generation_id)
├─ BodyTask：所有保留页结构化填充 → body.pptx
├─ DiagramTask：一图一个安全 SVG → diagram SVGs
└─ ComposeTask：依赖前两项 → composed.pptx
```

核心约束：

- 多个文档的解析文本统一放入 `requirement_text`，没有优先级；
- “文档标题 + 至少20个连续 `-`”表示文档边界；
- 5万字告警、10万字拒绝，并检查模型上下文；
- 页面信息不足即删除，防编造不可被 custom requirements 覆盖；
- 固定章节标题不变，封面项目名等动态占位按输入填写；
- 背景图和右上角小 Logo 保留，其它模板图片删除；
- Logo 默认阈值：横向75%后、纵向20%内、面积不超过5%，均可配置；
- 图形不能覆盖文字或超出版面，放不下则复制章节版式；
- SVG 直接净化预览，不转换 PNG；
- 部分图形失败仍组装成功图形，状态为 `completed_with_warnings`；
- 已成功子任务和图形从 FTP 恢复，失败任务只继续缺失部分。

完整流程见 [ppt_body_diagram_separated_generation_plan.md](ppt_body_diagram_separated_generation_plan.md)。

## 3. LLM 客户端

### 3.1 动态模型和思考模式

- 接口 `options.model` 和 `options.enable_thinking` 可动态指定
- 不传时使用 env 默认值（`LLM_MODEL` / `enable_thinking=false`）
- 参数从 `request_payload_json` 中解析，经 `orchestration_service` → `slide_generation_service` / `pptx_builder_service` → `openai_like_client` 透传

### 3.2 重试机制

- `plan_single_page`、`generate_page_svg`、`generate_page_content` 均有 3 次外层重试
- `_call_llm` 内层有独立的限流退避重试（`LLM_RATE_LIMIT_MAX_RETRIES`）
- 429 限流：优先读 `Retry-After` 头，无则指数退避 + 随机抖动
- 网络错误（ConnectError / ReadTimeout / WriteTimeout）：指数退避重试
- 退避延迟上限由 `LLM_RATE_LIMIT_MAX_DELAY` 控制
- 规划失败回退启发式；生成失败标记为 `failed` 不输出

### 3.3 流式支持

- 使用 `httpx2` 库
- 规划和生成均支持流式返回（`stream=True`）
- SSE 格式解析 `data: {...}` 行

### 3.4 全局并发控制

- `app/infrastructure/llm/concurrency.py` 提供全局信号量
- `bootstrap.build_services()` 启动时调用 `init_global_semaphore(MAX_LLM_CONCURRENCY)`
- 所有 LLM 请求（规划 + 生成，跨所有任务）共享同一个信号量
- `_call_llm` 中 acquire/release，异常时也保证释放
- 信号量在重试期间持续持有，避免重试时并发数超限

## 4. 检查规则注入

### 4.1 规则文件

`app/config/check_rules.json` 包含 66 条检查规则，涵盖文档标准化、架构设计、技术架构、数据架构、安全架构、非功能设计、工作量及实施计划等方面。每条规则包含 `id`、`category`、`check_point`、`requirement`、`keywords`、`page_purposes` 字段。

### 4.2 RuleMatcher

`app/infrastructure/llm/rule_matcher.py` 在每页处理时根据页面信息匹配适用规则：

- **专有关键词**匹配页名和元素内容
- **大类关键词**仅匹配页名（作为 fallback，避免遗漏）
- 匹配结果格式化为文本，注入到规划阶段和生成阶段的 system prompt 中

### 4.3 自定义要求（custom_requirements）

创建任务时可通过 `custom_requirements` 字段传入用户自定义的额外要求。该字段随 `request_payload_json` 持久化到数据库，运行时注入到每页的规划和生成提示词中（system prompt 和 user prompt）。

### 4.4 全局页面生成规范【已落地】

`app/config/page_generation_rules.json` 按模板固定章节标题匹配正向生成规范，不提供在线维护接口。优先级由低到高：模板要求 → `check_rules.json` → `page_generation_rules.json` → `custom_requirements`；防编造始终是不可覆盖的硬规则。

## 5. 存储策略

### 5.1 FTP 存储

- `FTP_HOST` 留空时：仅使用本地 `mock_ftp/`
- `FTP_HOST` 配置时：远程 FTP + 本地 mock_ftp 双写
- `MOCK_FTP_ENABLED=false`：关闭 mock_ftp 写入，仅用远程 FTP

### 5.2 Runtime 清理

- `runtime/tasks/{task_id}/` 在任务完成或失败后自动清理（`shutil.rmtree`）
- 所有产物已上传 FTP，runtime 仅作为运行时工作区

## 6. 模板策略

- 公共模板：`is_builtin=1`，所有调用方可使用
- 私有模板：带 `api_key` 归属，仅限所属调用方
- 默认模板：项目根目录 `templete.pptx`，启动时自动导入
- 模板主表示为 SVG 工作区（`svg/` + `svg-flat/`）
- 模板规则文件 `template_rules.json` 定义每页的元素结构和填充策略

## 7. Prompt 设计要点

### 7.1 规划 Prompt（prompt_builder.py）

- 明确要求封面/尾页/目录页 `should_generate=true`
- 要求输出纯 JSON（无 markdown 代码块）
- 判断依据：模板 SVG 文字内容 + 需求文本匹配度
- 支持注入检查规则和自定义要求

### 7.2 SVG 生成 Prompt（prompt_builder.py）

- 直接输出完整 SVG，不输出 JSON 或解释
- 排版规则：参考模板 y 坐标、行间距 24-28px、内容不超 viewBox
- **文本框规则**：同一内容区域的多行文字用一个 `<text>` + 多个 `<tspan>` 实现
- 按 page_type 添加特殊要求（cover/toc/diagram/end/content）
- 支持注入检查规则和自定义要求

### 7.3 结构化生成 Prompt（structured_prompt_builder.py）

- 严格输出 JSON，包含 `should_generate`、`skip_reason`、`elements`
- 只允许输出 text 和 table 两类元素
- 模板说明文字不可直接照抄，需改写为真实业务内容
- 支持内容溢出自动拆页
- 支持注入检查规则和自定义要求

### 7.4 新模式 Prompt【待实现】

- 共享规划输出信息充分性、是否保留、图形需求和 requirement_text 原文证据；
- 正文 Prompt 只允许 text/table，禁止生成或修改固定章节标题；
- 图形 Prompt 只输出一个图形 SVG，不包含整页背景、页脚和章节正文；
- 所有页面携带完整 requirement_text；
- 标题与连续长横线作为文档边界，不代表优先级。

## 8. 图标资源

`app/vendor/ppt_master/templates/icons/` 下的 SVG 图标被以下脚本使用：

- `scripts/svg_finalize/embed_icons.py`：将 `<use data-icon="...">` 替换为实际 SVG
- `scripts/svg_to_pptx/use_expander.py`：转 PPTX 时内存中展开图标引用

**不能移除该目录。**

## 9. 辅助脚本

`scripts/` 目录下包含规则相关的辅助脚本：

- `convert_check_rules.py`：将 `check_rules.txt` 转换为 `check_rules.json`
- `verify_rule_coverage.py`：验证规则匹配覆盖率
- `coverage_summary.py`：输出规则覆盖统计摘要
- `check_json_quality.py`：检查 `check_rules.json` 数据质量

## 10. 相关文档

- [API 接口文档（含新模式前端契约）](api_reference.md)
- [正文与单图 SVG 分离生成计划 v4](ppt_body_diagram_separated_generation_plan.md)
- [架构设计](fastapi_service_architecture.md)
- [持久化设计](mysql_ftp_persistence_design_v2.md)
- [并发设计](concurrency_design.md)
- [检查规则注入方案](check_rules_injection_design.md)
- [问题修复记录](bugfix_log.md)
- `sql/mysql_init_v2.sql`：当前初始化建表脚本；新模式需新增增量迁移
