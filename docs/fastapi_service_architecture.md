# FastAPI 服务架构说明

> 文档版本：v4，更新日期：2026-09-01
>
> **状态说明**：本文同时记录当前已实现的 `legacy_hybrid` 架构，以及已确认、待代码实现的 `separated_body_diagram` 目标架构。目标内容均明确标注“待实现”。

## 1. 文档目标

本文档描述项目当前架构与分离生成模式的目标架构，包括分层结构、核心流程、模块职责和关键技术决策。API 精确契约以 [api_reference.md](api_reference.md) 为准。

## 2. 技术栈

- **Web 框架**：FastAPI + Uvicorn
- **HTTP 客户端**：httpx2（支持流式 SSE）
- **数据模型**：Pydantic v2
- **数据库**：MySQL（通过 PyMySQL）
- **存储**：FTP + 本地 mock_ftp
- **PPT 转换**：内置 ppt_master 脚本（pptx_to_svg / svg_to_pptx / svg_finalize）
- **包管理**：uv
- **测试**：pytest + FastAPI TestClient

## 3. 分层架构

```text
API 层 (app/api/v1/endpoints/)
  ↓ 参数校验、请求转发
应用服务层 (app/services/)
  ↓ 任务编排、状态管理
基础设施层 (app/infrastructure/)
  ↓ LLM 调用、数据库、FTP、PPT 转换
内置运行时 (app/vendor/ppt_master/)
```

### 3.1 API 层

- `health.py`：健康检查
- `tasks.py`：任务 CRUD、停止/恢复、下载
- `templates.py`：模板导入和查询
- **【待实现】`generations.py`**：创建不可变生成输入、聚合查询、补触发子任务
- **【待实现】`diagrams.py`**：独立 SVG 图形详情、预览和下载

### 3.2 应用服务层

- `orchestration_service.py`：任务全生命周期编排（核心）
- `slide_generation_service.py`：逐页规划和生成调度
- `task_service.py`：任务数据库操作
- `template_service.py`：模板查询和 SVG 复制
- `template_import_service.py`：PPTX→SVG 模板导入
- `svg_validation_service.py`：SVG 语法校验
- `pptx_export_service.py`：SVG→PPTX 导出
- `bootstrap.py`：依赖注入和组装
- **【待实现】GenerationService**：冻结输入、创建 BodyTask/DiagramTask、满足依赖后创建 ComposeTask
- **【待实现】BodyGenerationService**：所有保留页结构化填充、图片清理、正文 PPT
- **【待实现】DiagramGenerationService**：一图一个 SVG、直接预览产物
- **【待实现】CompositionService**：图形局部放置、续页、部分成功组装

### 3.3 基础设施层

- `infrastructure/llm/`：LLM 客户端（OpenAI 风格 API）+ 全局并发信号量
- `infrastructure/db/`：MySQL 适配
- `infrastructure/storage/ftp.py`：FTP/mock_ftp 存储
- `infrastructure/ppt_master/`：PPT 转换适配器

## 4. 核心流程

```text
POST /api/v1/tasks
→ 创建任务记录到 MySQL
→ 后台启动 orchestration_service.run_task()
→ 加载模板，复制 SVG 到任务工作区
→ 解析 options.model / options.enable_thinking
→ ThreadPoolExecutor 并发提交所有页面
  每页独立处理：
    规划（plan_single_page）→ JSON 结果
    生成（generate_page_svg）→ SVG 直出
    SVG 校验
  全局信号量控制 LLM 请求总并发
  429 限流退避 + 网络错误退避
→ 导出 PPTX
→ 上传产物到 FTP
→ 清理 runtime 任务目录
→ 更新任务状态为 completed
```

以上是当前已实现的旧模式。

### 4.1 分离生成目标流程【待实现】

```text
POST /api/v1/generations
→ 创建 sg_generation_request，冻结 requirement_text、模板和参数
→ 按 targets 创建 BodyTask 和/或 DiagramTask
→ 首个子任务生成并持久化共享 planning_manifest
│
├─ BodyTask（与 DiagramTask 平级）
│  ├─ 只保留 requirement_text 足以填写的模板页
│  ├─ 所有保留页结构化生成文字/表格
│  ├─ 保留整页背景图和右上角 Logo，删除其它模板图片
│  └─ 输出 body.pptx + page_manifest.json
│
├─ DiagramTask（与 BodyTask 平级）
│  ├─ 为信息充足且模板要求的图形生成独立 SVG
│  ├─ 一图一个 SVG；SVG-only 不展示页码
│  ├─ 安全净化后直接提供 image/svg+xml 预览
│  └─ 输出 diagram SVG + diagram_manifest.json
│
└─ ComposeTask（依赖前两项）
   ├─ auto_compose=true 且正文、图形可用时自动创建
   ├─ 图形不超版面、不覆盖文字；放不下则复制章节版式
   ├─ 部分图形失败时使用成功图形继续组装
   └─ 输出 composed.pptx，状态可为 completed_with_warnings
```

任务层级：一个 `generation_id` 关联平级的 BodyTask/DiagramTask，ComposeTask 是下游依赖。输入改变时创建新的 generation，不允许执行中修改。

## 5. 任务状态机

```
pending → running → completed
                   → failed
running → stopping → stopped
stopped → resuming → running
```

旧模式阶段（current_stage）：
- `queued` → `preparing` → `page_planning` → `page_generation` → `validating` → `exporting` → `completed`
- 异常时：`failed`

新模式【待实现】：

- Generation 聚合状态：`pending/running/completed/completed_with_warnings/failed`
- Body/Diagram 子状态：`not_requested/pending/running/completed/completed_with_warnings/failed`
- Compose 子状态：`not_requested/waiting/pending/running/completed/completed_with_warnings/failed`
- task_type：`legacy/body/diagrams/compose`

完整枚举见 [api_reference.md 第4.2节](api_reference.md#42-枚举值总表)。

## 6. LLM 两阶段生成

### 6.1 规划阶段（plan_single_page）

每页独立请求 LLM，输入：
- 完整需求文本
- 当前页模板 SVG 内容
- 页码和页面名称

LLM 返回 JSON：
```json
{
  "should_generate": true,
  "skip_reason": "",
  "page_type": "content",
  "page_title": "系统架构总览"
}
```

规则：
- 封面/尾页/目录页始终 `should_generate=true`
- `page_type` 取值：cover / toc / content / diagram / end
- 失败重试 3 次，仍失败回退启发式逻辑

### 6.2 生成阶段（generate_page_svg）

每页独立请求 LLM，输入：
- 完整需求文本
- 当前页模板 SVG 内容
- 规划结果（page_type, page_title）

LLM 直接输出完整 SVG 代码（非 JSON）。

失败处理：
- 重试 3 次，仍失败则 `decision_source=failed`
- 失败页面不输出到最终 PPTX

### 6.3 新模式 LLM 阶段【待实现】

1. **共享规划**：完整 `requirement_text` + 模板固定章节标题与填写要求 → `should_keep/information_sufficient/diagram_required/diagram_kind/reason/evidence_quotes`。
2. **正文生成**：所有保留页只输出结构化 text/table JSON，不允许生成整页 SVG，不允许改固定章节名。
3. **图形生成**：只输出一个独立图形 SVG，不包含整页背景、章节标题、页脚或正文。
4. **防编造**：只能使用 requirement_text 中明确存在的事实；该规则不可被 custom_requirements 覆盖。
5. **文档边界**：标题后的至少20个连续 `-` 表示新文档开始，不产生优先级。
6. **长度限制**：5万字告警、10万字拒绝，并检查模型 token 上限。

### 6.4 全局并发控制

- **全局信号量**：`app/infrastructure/llm/concurrency.py` 提供 `threading.Semaphore`
- **初始化**：`bootstrap.build_services()` 调用 `init_global_semaphore(MAX_LLM_CONCURRENCY)`
- **作用范围**：所有任务的 LLM 请求（规划 + 生成）共享同一个信号量
- **实现位置**：`_call_llm` 方法中 acquire/release，finally 确保释放
- **重试期间**：信号量持续持有，避免重试导致并发数超限

### 6.5 限流退避机制

- **429 限流**：优先读 `Retry-After` 响应头，无则指数退避 + 随机抖动
- **网络错误**：`ConnectError` / `ReadTimeout` / `WriteTimeout` 指数退避重试
- **配置项**：
  - `LLM_RATE_LIMIT_MAX_RETRIES`：最大重试次数
  - `LLM_RATE_LIMIT_BASE_DELAY`：基准延迟
  - `LLM_RATE_LIMIT_MAX_DELAY`：延迟上限

### 6.6 动态模型参数

- `options.model`：不传时使用 env `LLM_MODEL`
- `options.enable_thinking`：不传时默认 `false`
- 参数透传链路：API → request_payload_json → orchestration_service → slide_generation_service → openai_like_client → _call_llm

## 7. 存储设计

### 7.1 FTP 路径结构

```text
/slides_gen_server/
├─ templates/{template_id}/
│  ├─ source/template.pptx
│  ├─ imported/svg/
│  ├─ imported/svg-flat/
│  └─ manifest/template_manifest.json
└─ tasks/{task_id}/
   ├─ request/request.json
   ├─ input/requirement.md
   ├─ analysis/page_plans.json
   ├─ analysis/page_01.json
   ├─ svg_output/slide_1.svg
   ├─ svg_final/slide_1.svg
   ├─ validation/svg_validation_report.json
   └─ exports/generated.pptx
```

新模式【待实现】：

```text
/generations/{generation_id}/
├─ request/request.json
├─ input/requirement.md
└─ analysis/planning_manifest.json

/tasks/{body_task_id}/exports/body.pptx
/tasks/{body_task_id}/analysis/page_manifest.json
/tasks/{diagram_task_id}/diagrams/{diagram_id}.svg
/tasks/{diagram_task_id}/analysis/diagram_manifest.json
/tasks/{compose_task_id}/exports/composed.pptx
```

所有产物长期保存在 FTP，不设置自动过期；数据库只保存元数据和 FTP 路径。

### 7.2 MOCK_FTP_ENABLED

- `true`（默认）：所有上传操作同时写入本地 `mock_ftp/`
- `false`：不写入本地 mock_ftp，仅写远程 FTP（需配置 `FTP_HOST`）

### 7.3 Runtime 清理

- `runtime/tasks/{task_id}/` 在任务完成或失败后自动 `shutil.rmtree`
- 所有产物已上传 FTP，runtime 仅作为运行时工作区

## 8. 接口设计

### 8.1 通用响应格式

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

### 8.2 创建任务

```
POST /api/v1/tasks
Header: X-LLM-API-Key: {api_key}
```

```json
{
  "requirement_text": "需求全文",
  "template_id": null,
  "options": {
    "output_filename": "demo.pptx",
    "model": "qwen3.6-27b",
    "enable_thinking": false,
    "max_page_concurrency": 4,
    "keep_artifacts": true
  }
}
```

以上为当前已实现旧模式。

### 8.3 创建分离生成输入【待实现】

```text
POST /api/v1/generations
GET  /api/v1/generations
GET  /api/v1/generations/{generation_id}
POST /api/v1/generations/{generation_id}/tasks
```

核心请求字段：

- `generation_mode=separated_body_diagram`
- `targets=[body, diagrams]`
- `auto_compose=true`
- `requirement_text`：多个文档合并后的纯文本
- `custom_requirements`：当前任务生成指令

任务与图形查询、预览、下载接口见 [api_reference.md 第4节](api_reference.md#4-分离生成模式新增待实现)。

### 8.4 查询接口

| 接口 | 说明 |
|------|------|
| `GET /api/v1/tasks` | 任务列表（支持 `ids_only`、`status` 过滤） |
| `GET /api/v1/tasks/{task_id}` | 任务详情 |
| `GET /api/v1/tasks/{task_id}/pages` | 分页状态 |
| `GET /api/v1/tasks/{task_id}/events` | 任务事件 |
| `GET /api/v1/tasks/{task_id}/artifacts` | 任务产物 |
| `GET /api/v1/tasks/{task_id}/download` | 下载 PPTX |
| `POST /api/v1/tasks/{task_id}/stop` | 停止任务 |
| `POST /api/v1/tasks/{task_id}/resume` | 恢复任务 |
| **`GET /api/v1/generations/{generation_id}/diagrams`** | **【待实现】图形列表** |
| **`GET /api/v1/tasks/{task_id}/diagrams/{diagram_id}/preview`** | **【待实现】直接 SVG 预览** |
| **`GET /api/v1/tasks/{task_id}/diagrams/{diagram_id}/download`** | **【待实现】SVG 下载** |
| **`GET /api/v1/tasks/{task_id}/artifacts/{artifact_id}/download`** | **【待实现】精确产物下载** |

## 9. 数据库表

| 表名 | 说明 |
|------|------|
| `sg_template` | 模板元数据 |
| `sg_generation_task` | 任务主记录 |
| `sg_generation_task_page` | 分页生成状态 |
| `sg_generation_task_artifact` | 产物 FTP 路径 |
| `sg_generation_task_event` | 任务事件日志 |
| **`sg_generation_request`** | **【待实现】不可变输入、三个子任务 ID 与聚合状态** |
| **`sg_generation_diagram`** | **【待实现】一图一行的 SVG metadata 和 FTP 路径** |

当前 DDL 文件：`sql/mysql_init_v2.sql`。新模式实现时需新增增量迁移，不能只修改初始化脚本。

## 10. 配置项

| 变量 | 说明 |
|------|------|
| `API_KEY` | LLM API Key |
| `BASIC_MODEL` / `LLM_MODEL` | 默认 LLM 模型 |
| `HOST` / `LLM_BASE_URL` | LLM API 地址 |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_SCHEMA` | MySQL |
| `FTP_HOST` / `FTP_PORT` / `FTP_USER` / `FTP_PASSWORD` | 远程 FTP |
| `FTP_ROOT_DIR` | FTP 根目录 |
| `MOCK_FTP_ENABLED` | 是否写 mock_ftp |
| `MOCK_FTP_DIR` | mock_ftp 本地路径 |
| `DEFAULT_TEMPLATE_FILE` | 默认模板 PPTX |
| `DEFAULT_TEMPLATE_ID` | 默认模板 ID |
| `LLM_TIMEOUT_SECONDS` | LLM 超时 |
| `MAX_LLM_CONCURRENCY` | 全局 LLM 请求最大并发数 |
| `LLM_RATE_LIMIT_MAX_RETRIES` | 429/网络错误最大重试次数 |
| `LLM_RATE_LIMIT_BASE_DELAY` | 退避基准延迟秒数 |
| `LLM_RATE_LIMIT_MAX_DELAY` | 退避最大延迟秒数 |
| **`REQUIREMENT_TEXT_WARN_CHARS`** | **【待实现】需求文本告警字符数，默认50000** |
| **`REQUIREMENT_TEXT_MAX_CHARS`** | **【待实现】需求文本上限，默认100000** |
| **`DOCUMENT_SEPARATOR_MIN_HYPHENS`** | **【待实现】文档边界横线数量，默认20** |
| **`LOGO_RIGHT_START_RATIO`** | **【待实现】Logo 横向起点，默认0.75** |
| **`LOGO_TOP_END_RATIO`** | **【待实现】Logo 纵向上限，默认0.20** |
| **`LOGO_MAX_AREA_RATIO`** | **【待实现】Logo 最大面积比例，默认0.05** |

## 11. 测试

```bash
uv run pytest tests/ -x -q
```

测试覆盖：
- FTP 存储（mock 模式、上传下载、MOCK_FTP_ENABLED 开关）
- 请求/响应模型校验（含 model/enable_thinking 字段）
- 任务 API（创建、查询、停止、恢复）
- 模板 API（导入、查询）
- SVG 校验服务
- LLM 客户端（重试逻辑、参数透传、SVG 提取）
- 并发控制（全局信号量、429 退避、网络错误退避、退避计算）
- Prompt 构建器
- 幻灯片生成服务
