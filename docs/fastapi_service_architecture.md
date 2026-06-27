# FastAPI 接口与项目架构详细设计

## 1. 文档目标

本文档定义新项目的工程实现蓝图，重点说明：

- 接口怎么设计
- 异步任务怎么运行
- 项目目录怎么组织
- 模板、SVG、PPTX 的数据流怎么走
- 参考实现能力如何迁入项目自身目录并解耦复用

这份文档是后续代码实现的直接依据。

## 2. 设计原则

## 2.1 总原则

新项目必须遵循以下原则：

- 使用**标准 FastAPI 服务架构**
- 使用**异步任务模式**处理长耗时生成
- 以 **SVG 作为模板与页面生成的核心中间表示**
- 以 `svg_to_pptx` 作为最终 PPTX 输出适配器
- 不沿用旧版 `refs/pptx_gen` 的脚本式主架构
- 参考代码只用于对照设计，运行时代码必须迁入项目自身目录

## 2.2 技术原则

- HTTP 层使用 `async def`
- 大模型调用使用异步客户端
- 多页并发使用 `asyncio` 并结合并发上限控制
- 长任务通过后台任务管理器执行，不让请求长时间阻塞
- 领域逻辑、服务编排、底层适配器严格分层

## 3. 总体架构

## 3.1 逻辑分层

```text
API 层
↓
应用服务层
↓
领域层
↓
基础设施层 / 外部适配器层
```

### 3.1.1 API 层

负责：
- 接收 HTTP 请求
- 参数校验
- 返回标准响应
- 不直接写业务细节

### 3.1.2 应用服务层

负责：
- 组织任务流程
- 调用模板服务、页面生成服务、SVG 校验服务、PPT 导出服务
- 管理任务状态流转

### 3.1.3 领域层

负责：
- 表达核心业务对象
- 表达页面判定、模板页、SVG 页面、任务结果等概念
- 封装核心规则，不依赖具体框架

### 3.1.4 基础设施层 / 适配器层

负责：
- 调用 LLM
- 调用 `pptx_to_svg`
- 调用 `svg_to_pptx`
- 文件存储
- 本地任务仓库
- 日志与配置

## 3.2 核心流程图

```text
POST /generation-jobs
-> 创建任务记录
-> 后台启动编排器
-> 选择默认模板或加载自定义模板
-> 模板 PPTX -> SVG 工作区
-> 分页并发生成
-> 每页生成判定 should_generate
-> 生成受控 SVG
-> SVG 校验
-> 汇总到项目工作区
-> 调用 svg_to_pptx
-> 产出 PPTX
-> 更新任务状态 completed/failed
```

## 4. 标准项目目录设计

建议的新项目目录如下：

```text
slides_gen_server/
├─ app/
│  ├─ api/
│  │  ├─ deps.py
│  │  └─ v1/
│  │     ├─ router.py
│  │     └─ endpoints/
│  │        ├─ health.py
│  │        ├─ templates.py
│  │        └─ generation_jobs.py
│  ├─ core/
│  │  ├─ config.py
│  │  ├─ logging.py
│  │  ├─ exceptions.py
│  │  └─ constants.py
│  ├─ schemas/
│  │  ├─ common.py
│  │  ├─ template.py
│  │  ├─ generation.py
│  │  └─ job.py
│  ├─ domain/
│  │  ├─ entities/
│  │  │  ├─ template.py
│  │  │  ├─ slide.py
│  │  │  ├─ svg_page.py
│  │  │  └─ generation_job.py
│  │  ├─ value_objects/
│  │  │  ├─ page_decision.py
│  │  │  └─ artifact.py
│  │  └─ services/
│  │     ├─ page_decision_service.py
│  │     └─ svg_contract_service.py
│  ├─ services/
│  │  ├─ template_service.py
│  │  ├─ template_import_service.py
│  │  ├─ slide_generation_service.py
│  │  ├─ svg_validation_service.py
│  │  ├─ pptx_export_service.py
│  │  ├─ generation_job_service.py
│  │  └─ orchestration_service.py
│  ├─ infrastructure/
│  │  ├─ llm/
│  │  │  ├─ base.py
│  │  │  ├─ openai_like_client.py
│  │  │  └─ prompt_builder.py
│  │  ├─ storage/
│  │  │  ├─ file_store.py
│  │  │  ├─ template_repository.py
│  │  │  └─ job_repository.py
│  │  ├─ tasking/
│  │  │  ├─ job_runner.py
│  │  │  └─ concurrency.py
│  │  ├─ svg/
│  │  │  ├─ svg_parser.py
│  │  │  ├─ svg_metadata.py
│  │  │  ├─ svg_merger.py
│  │  │  └─ svg_validator.py
│  │  ├─ ppt_master/
│  │  │  ├─ pptx_to_svg_adapter.py
│  │  │  ├─ svg_to_pptx_adapter.py
│  │  │  └─ project_workspace.py
│  │  └─ observability/
│  │     ├─ metrics.py
│  │     └─ tracing.py
│  ├─ vendor/
│  │  └─ ppt_master/
│  ├─ main.py
│  └─ __init__.py
├─ docs/
├─ runtime/
│  ├─ templates/
│  ├─ jobs/
│  └─ temp/
├─ mock_ftp/
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ fixtures/
├─ pyproject.toml
└─ README.md
```

## 5. 模块职责设计

## 5.1 `app/api`

### `generation_jobs.py`

负责：
- 创建生成任务
- 查询任务状态
- 下载任务结果
- 查询任务产物

### `templates.py`

负责：
- 导入模板
- 查询模板列表
- 查询模板详情

### `health.py`

负责：
- 健康检查
- 依赖状态检查

## 5.2 `app/services`

### `template_import_service.py`

负责：
- 接收用户上传的 PPTX 模板
- 调用 `pptx_to_svg` 导出 SVG 工作区
- 生成模板索引记录
- 保存模板元信息

### `template_service.py`

负责：
- 获取默认模板
- 查询模板详情
- 读取模板页 SVG
- 复用缓存好的模板工作区

### `slide_generation_service.py`

负责：
- 单页分析
- 单页判定 `should_generate`
- 生成目标页面 SVG
- 产出页级结果

### `svg_validation_service.py`

负责：
- 校验生成后的 SVG 是否在允许子集内
- 校验必要 `id` / `data-*` / `<metadata>` 是否齐全
- 校验是否存在 `svg_to_pptx` 不支持的危险元素

### `pptx_export_service.py`

负责：
- 将生成工作区组织成 `svg_to_pptx` 可直接消费的项目格式
- 调用 `svg_to_pptx`
- 产出最终 PPTX

### `generation_job_service.py`

负责：
- 创建、更新、读取任务记录
- 管理任务状态、进度、错误信息和产物索引

### `orchestration_service.py`

负责：
- 串起整个任务生命周期
- 控制分页并发
- 控制异常处理、失败回收、日志和最终状态

## 5.3 `app/infrastructure/ppt_master`

这一层是新服务与参考项目 `ppt-master` 的隔离层。

### `pptx_to_svg_adapter.py`

负责：
- 封装 `pptx_to_svg` 调用
- 只向上层暴露“给我模板 PPTX，返回模板 SVG 工作区”这种服务接口
- 不让上层业务直接耦合脚本细节

### `svg_to_pptx_adapter.py`

负责：
- 封装 `svg_to_pptx` 调用
- 负责将工作区路径转换为最终 PPTX 输出

### `project_workspace.py`

负责：
- 生成符合 `svg_to_pptx` 期望的目录结构
- 管理 `svg_output/`、`svg_final/`、`exports/`、`notes/` 等目录

## 6. 运行时数据目录设计

为了兼容 `ppt-master` 的项目工作区习惯，建议统一用如下运行时目录：

```text
runtime/
├─ templates/
│  └─ {template_id}/
│     ├─ source/
│     │  └─ template.pptx
│     ├─ imported/
│     │  ├─ svg/
│     │  ├─ svg-flat/
│     │  ├─ assets/
│     │  └─ inheritance.json
│     ├─ manifest/
│     │  └─ template_manifest.json
│     └─ preview/
├─ jobs/
│  └─ {job_id}/
│     ├─ request/
│     │  └─ request.json
│     ├─ input/
│     │  └─ requirement.md
│     ├─ template_snapshot/
│     ├─ analysis/
│     │  ├─ page_01.json
│     │  ├─ page_02.json
│     │  └─ ...
│     ├─ svg_output/
│     │  ├─ 01_xxx.svg
│     │  ├─ 02_xxx.svg
│     │  └─ ...
│     ├─ svg_final/
│     │  ├─ 01_xxx.svg
│     │  ├─ 02_xxx.svg
│     │  └─ ...
│     ├─ validation/
│     │  └─ svg_validation_report.json
│     ├─ exports/
│     │  └─ generated.pptx
│     └─ manifest/
│        ├─ job.json
│        └─ artifacts.json
└─ temp/
```

说明：

- `templates/` 用于缓存模板导入结果
- `jobs/` 用于保存每次生成任务的完整过程产物
- `svg_output/` 作为原始生成 SVG
- `svg_final/` 作为校验或后处理后的最终 SVG
- `exports/` 存最终 PPTX

## 7. 模板设计

## 7.1 默认模板

默认模板在系统配置中注册，例如：

- `default_template_id = "builtin-default"`

其工作方式：
- 服务启动时加载默认模板配置
- 若缓存中不存在导入结果，则自动进行一次模板导入预处理
- 生成任务未传模板参数时直接复用该模板

## 7.2 自定义模板导入

建议模板导入流程：

```text
上传 PPTX -> 生成 template_id -> 保存源文件
-> 调用 pptx_to_svg --inheritance-mode both
-> 保存导入结果
-> 生成模板清单
-> 返回 template_id
```

## 7.3 模板清单设计

虽然模板主链路不是 JSON，但工程上仍建议维护一个**轻量清单**，用于查询和调度，不作为唯一模板真相来源。

建议字段：

- `template_id`
- `template_name`
- `source_pptx_path`
- `imported_svg_dir`
- `imported_svg_flat_dir`
- `slide_count`
- `default_slide_size`
- `created_at`
- `is_builtin`
- `status`

注意：
- 清单是**缓存索引**
- 真正参与生成的页面来源仍然是 SVG 文件本身

## 8. SVG 页面设计

## 8.1 页面组成原则

每个最终页面 SVG 分为两部分：

- **保留层**：模板静态背景、静态图标、静态图片、装饰元素
- **生成层**：本次任务需要替换或新增的文本和图形

## 8.2 推荐结构

```xml
<svg>
  <metadata>{...}</metadata>
  <g id="page-background" data-gen-editable="false">...</g>
  <g id="page-static-assets" data-gen-editable="false">...</g>
  <g id="title-block" data-gen-role="title" data-gen-editable="true">...</g>
  <g id="body-block" data-gen-role="body" data-gen-editable="true">...</g>
  <g id="diagram-block" data-gen-role="diagram" data-gen-editable="true">...</g>
</svg>
```

## 8.3 元数据策略

### 8.3.1 页面级 `<metadata>`

用于保存整页信息，如：

- `job_id`
- `template_id`
- `page_no`
- `page_name`
- `should_generate`
- `generation_mode`
- `diagram_kind`

### 8.3.2 元素级 `data-*`

用于保存局部含义，如：

- `data-gen-role="title"`
- `data-gen-binding="requirement.summary"`
- `data-gen-editable="true"`
- `data-gen-source="llm"`
- `data-gen-kind="sequence"`

## 8.4 为什么不用注释

不建议使用 `<!-- -->` 注释保存关键元数据，原因：

- 当前 `svg_to_pptx` 解析链路基于 `ElementTree`
- 注释不是稳定的业务数据结构
- 对后续校验、编辑、排障都不友好

结论：
- **注释可以用于人工阅读提示**
- **不能作为系统关键依赖字段**

## 9. 页面判定与生成设计

## 9.1 单页判定结果

每页必须产出统一结果结构：

```json
{
  "page_no": 1,
  "page_name": "系统架构总览",
  "should_generate": true,
  "skip_reason": "",
  "diagram_kind": "architecture",
  "generated_svg_path": "runtime/jobs/{job_id}/svg_output/01_arch.svg"
}
```

## 9.2 保留旧业务原则

沿用旧版最关键的判断逻辑：

- 不是每页都必须生成
- 不适合当前需求的页面应删除
- 要清楚记录跳过原因

这意味着最终 `svg_to_pptx` 输入的页面集合，应该只包含：

- 原模板中需要保留且成功生成的页
- 或者需要保留的原样页（若设计上允许）

本阶段建议优先采用：
- **仅输出 should_generate=true 的页面到最终工作区**

## 9.3 分页并发策略

建议：

- 任务内部按页并发
- 使用 `asyncio.Semaphore` 控制最大并发数
- 并发数由配置控制，例如 `max_page_concurrency=4`

原因：
- 大模型调用多，天然适合并发
- 但并发过高会导致 API 限流或成本失控

## 10. 接口设计

## 10.1 通用响应约定

统一响应字段建议：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

错误时：

```json
{
  "code": 40001,
  "message": "template file is invalid",
  "data": null
}
```

## 10.2 健康检查接口

### `GET /api/v1/health`

作用：
- 检查服务是否在线
- 可扩展检查 LLM、文件系统、模板目录状态

返回示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "status": "healthy"
  }
}
```

## 10.3 模板列表接口

### `GET /api/v1/templates`

作用：
- 查询可用模板

响应字段：
- `template_id`
- `template_name`
- `is_builtin`
- `slide_count`
- `status`
- `created_at`

## 10.4 模板导入接口

### `POST /api/v1/templates/import`

作用：
- 上传自定义模板 PPTX 并完成预处理

请求方式：
- `multipart/form-data`

请求参数：
- `template_name`: string
- `template_file`: file

响应示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "template_id": "tpl_20260624_xxxx",
    "template_name": "客户汇报模板",
    "slide_count": 12,
    "status": "ready"
  }
}
```

失败场景：
- 文件不是 pptx
- 模板导入失败
- `pptx_to_svg` 执行失败

## 10.5 模板详情接口

### `GET /api/v1/templates/{template_id}`

作用：
- 查询模板详情

响应字段建议：
- `template_id`
- `template_name`
- `is_builtin`
- `source_pptx_name`
- `slide_count`
- `status`
- `created_at`
- `artifact_paths`

## 10.6 创建生成任务接口

### `POST /api/v1/generation-jobs`

作用：
- 创建新的 PPT 生成任务

请求体建议：

```json
{
  "requirement_text": "请生成一份关于智能制造平台方案的汇报材料，包含背景、目标、总体架构、时序流程、实施计划。",
  "template_id": "builtin-default",
  "options": {
    "max_page_concurrency": 4,
    "keep_artifacts": true,
    "output_filename": "smart_factory_solution.pptx"
  }
}
```

字段说明：

- `requirement_text`
  - 类型：string
  - 必填
  - 含义：本次 PPT 生成需求全文

- `template_id`
  - 类型：string
  - 可选
  - 不传时使用默认模板

- `options.max_page_concurrency`
  - 类型：int
  - 可选
  - 含义：单任务页面最大并发

- `options.keep_artifacts`
  - 类型：bool
  - 可选
  - 含义：是否保留中间产物

- `options.output_filename`
  - 类型：string
  - 可选
  - 含义：输出文件名建议

返回示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "job_id": "job_20260624_xxxx",
    "status": "pending",
    "status_url": "/api/v1/generation-jobs/job_20260624_xxxx"
  }
}
```

## 10.7 查询任务状态接口

### `GET /api/v1/generation-jobs/{job_id}`

作用：
- 查询任务状态和进度

响应示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "job_id": "job_20260624_xxxx",
    "status": "running",
    "progress": 62,
    "current_stage": "generating_svg_pages",
    "template_id": "builtin-default",
    "total_pages": 12,
    "processed_pages": 8,
    "error_message": null,
    "result": null
  }
}
```

## 10.8 查询任务产物接口

### `GET /api/v1/generation-jobs/{job_id}/artifacts`

作用：
- 查询任务中间产物与最终产物路径信息

响应字段建议：
- `request_path`
- `analysis_dir`
- `svg_output_dir`
- `svg_final_dir`
- `validation_report_path`
- `pptx_path`

## 10.9 下载结果接口

### `GET /api/v1/generation-jobs/{job_id}/download`

作用：
- 下载最终 PPTX 文件

成功行为：
- 返回 `application/vnd.openxmlformats-officedocument.presentationml.presentation`

失败行为：
- 任务未完成
- 文件不存在
- 任务失败

## 10.10 可选的任务取消接口

### `POST /api/v1/generation-jobs/{job_id}/cancel`

作用：
- 尝试取消未完成任务

说明：
- 不是本阶段必须实现
- 但状态机设计建议预留

## 11. 任务状态机设计

建议状态：

- `pending`
- `running`
- `completed`
- `failed`
- `cancelled`

建议阶段：

- `queued`
- `preparing_template`
- `analyzing_pages`
- `generating_svg_pages`
- `validating_svg_pages`
- `building_pptx`
- `finalizing`
- `done`

状态流转：

```text
pending
-> running / queued
-> running / preparing_template
-> running / analyzing_pages
-> running / generating_svg_pages
-> running / validating_svg_pages
-> running / building_pptx
-> completed / done
或
-> failed
或
-> cancelled
```

## 12. 与 `ppt-master` 的适配设计

## 12.1 `pptx_to_svg` 的使用方式

建议调用方式：

- 使用 `inheritance-mode both`
- 同时保留：
  - `svg/` layered 结构
  - `svg-flat/` 平铺预览结构

原因：
- layered 更适合机器识别模板贡献层
- flat 更适合视觉校对和调试

## 12.2 `svg_to_pptx` 的使用方式

建议使用 native 主模式：

- 目标是把 SVG 转成尽量可编辑的 DrawingML 形状
- 最终工作区优先提供 `svg_output/`
- 如存在必要清洗，再生成 `svg_final/`

## 12.3 与新服务的职责边界

`ppt-master` 负责：
- PPTX <-> SVG 的转换能力

新服务负责：
- 模板管理
- 页面判定
- SVG 生成
- SVG 约束校验
- 任务编排
- API 输出

也就是说：
- **新服务不直接把 `ppt-master` 当业务主程序使用**
- **新服务只把它当底层能力适配器使用**

## 13. LLM 生成设计

## 13.1 LLM 输入

每页生成时，输入建议包含：

- 全局需求文本
- 当前页模板参考图
- 当前页可编辑区域说明
- 当前页静态保留元素说明
- SVG 子集限制
- 输出结构要求

## 13.2 LLM 输出

建议输出不要直接是一大段自由 SVG 字符串，而应采用“两段式”结果：

### 方式 A：结构化中间结果 + SVG 渲染器

```json
{
  "page_no": 4,
  "should_generate": true,
  "skip_reason": "",
  "page_title": "总体架构",
  "diagram_kind": "architecture",
  "nodes": [...],
  "edges": [...],
  "texts": [...]
}
```

然后由服务端把结构化对象渲染成受控 SVG。

### 方式 B：受控 SVG 直出

```json
{
  "page_no": 4,
  "should_generate": true,
  "skip_reason": "",
  "svg": "<svg>...</svg>"
}
```

## 13.3 本阶段推荐方案

推荐优先使用：

- **图形页：结构化中间结果 -> 服务端 SVG 渲染器**
- **文本页：结构化文本块 -> 服务端拼接 SVG**

不建议一开始就让模型完全自由直出 SVG，原因：

- 难控制语法范围
- 难保证 `svg_to_pptx` 可转化率
- 难排查失败原因

## 14. SVG 约束设计

## 14.1 白名单规则

生成器最终输出前必须执行白名单校验：

- 只允许指定标签
- 只允许指定属性
- `id` 必须唯一
- `data-*` 属性只允许约定前缀
- 禁止脚本、foreignObject、外链资源

## 14.2 分组规则

为了让 PowerPoint 动画和后续编辑更稳定，建议：

- 顶层按语义分组 `g`
- 每个主要图形模块保持单独 `id`
- 背景与静态装饰单独归组

例如：
- `page-background`
- `title-block`
- `diagram-main`
- `legend-block`
- `footer-block`

## 14.3 文本规则

- 文本框应限制长度
- 使用受控字号和布局
- 避免非常复杂的嵌套 `tspan`

## 15. 错误处理设计

## 15.1 错误分类

建议分为：

- `template_error`
- `validation_error`
- `llm_error`
- `svg_generation_error`
- `pptx_export_error`
- `internal_error`

## 15.2 错误记录粒度

至少记录：

- 任务级错误
- 页面级错误
- 当前阶段
- 原始异常信息
- 对外友好错误文案

## 16. 配置设计

建议配置项：

- `APP_NAME`
- `APP_ENV`
- `API_PREFIX`
- `DEFAULT_TEMPLATE_ID`
- `RUNTIME_ROOT`
- `MAX_PAGE_CONCURRENCY`
- `KEEP_JOB_ARTIFACTS`
- `LLM_PROVIDER`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_API_KEY`
- `LLM_TIMEOUT_SECONDS`
- `SVG_TO_PPTX_TIMEOUT_SECONDS`
- `PPTX_TO_SVG_TIMEOUT_SECONDS`

## 17. 建议依赖

后续实现阶段建议引入：

- `fastapi`
- `uvicorn`
- `httpx`
- `python-multipart`
- `pydantic-settings`
- `python-pptx`
- `python-dotenv`

可选：
- `orjson`
- `tenacity`
- `structlog`
- `pytest`
- `pytest-asyncio`

## 18. 测试设计

## 18.1 单元测试

覆盖：
- 状态机流转
- 模板选择逻辑
- 默认模板回退逻辑
- 单页判定逻辑
- SVG 元数据生成逻辑
- SVG 白名单校验逻辑

## 18.2 集成测试

覆盖：
- 模板导入接口
- 生成任务接口
- 状态查询接口
- 下载接口
- `pptx_to_svg` 适配器调用
- `svg_to_pptx` 适配器调用

## 18.3 端到端测试

覆盖：
- 使用默认模板生成一份完整 PPT
- 使用自定义模板生成一份完整 PPT
- 图形页包含架构图 / 时序图的场景
- 跳页逻辑正确生效

## 19. 首版实现建议

为了降低风险，建议按以下顺序实现：

### 第一步

先实现：
- FastAPI 基础骨架
- 健康检查
- 模板列表
- 模板导入
- 任务创建 / 状态查询 / 下载的空骨架

### 第二步

接入：
- 默认模板
- `pptx_to_svg` 模板导入
- 任务目录结构

### 第三步

接入：
- 文本页生成
- 简单架构图页生成
- SVG 白名单校验

### 第四步

接入：
- `svg_to_pptx`
- 任务结果下载
- 日志和错误报告

### 第五步

再扩展：
- 时序图
- 流程图
- 更多模板兼容
- 任务取消和重试

## 20. 最终结论

新的项目架构应该是一个**标准分层 FastAPI 服务**，其核心不是“复刻旧脚本”，而是围绕下面三件事来建设：

- **模板主表示 = SVG 工作区**
- **生成主表示 = 受控可编辑 SVG**
- **服务主入口 = 异步任务 API**

一句话总结：

**让模板先变成 SVG，让模型生成可编辑 SVG，再把 SVG 还原成可编辑 PPT，并且全过程以 FastAPI 服务方式组织。**
