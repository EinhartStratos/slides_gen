# API 接口文档

> 文档版本：v4，更新日期：2026-09-01
>
> 基础路径：`/api/v1`
> 所有接口（除健康检查和模板列表外）需在请求头中携带 `X-LLM-API-Key`。
>
> **接口状态标记：**
> - **【已实现】**：当前后端代码已经提供，前端可直接联调；
> - **【新增·待实现】**：分离生成模式最终契约，供前端预先开发，当前后端尚未上线；
> - 未特别标记的原任务接口均为【已实现】。
>
> 新模式完整设计见 [PPT 正文与单图 SVG 分离生成计划](ppt_body_diagram_separated_generation_plan.md)。实现前后端时应保持本文件字段、枚举和样例一致。
>
> 统一响应格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": ...
}
```

- `code` 为 `0` 表示成功，非 `0` 表示业务错误
- `data` 的结构因接口而异，见各接口说明

---

## 1. 健康检查

### `GET /api/v1/health`

检查服务、数据库、FTP 的连通状态。无需鉴权。

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "status": "ok",
    "database": true,
    "ftp": true,
    "ftp_mode": "mock_only",
    "mock_ftp_dir": "C:\\AMD\\slides_gen_server\\mock_ftp"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `"ok"` 或 `"degraded"` |
| `database` | bool | 数据库是否可连接 |
| `ftp` | bool | FTP 是否可连接 |
| `ftp_mode` | string | `"mock_only"` 或 `"remote+mock"` |
| `mock_ftp_dir` | string | mock_ftp 本地路径 |

---

## 2. 模板管理

### 2.1 查询模板列表

### `GET /api/v1/templates`

返回所有可访问的模板（内置 + 当前 API Key 的私有模板）。可选鉴权。

**请求示例：**

```bash
curl http://127.0.0.1:8000/api/v1/templates
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "template_id": "tpl_20260627132835_bce99ff8",
      "template_name": "templete",
      "source_type": "builtin",
      "source_filename": "templete.pptx",
      "slide_count": 48,
      "status": "ready",
      "is_builtin": true,
      "created_at": "2026-06-27T13:28:37"
    }
  ]
}
```

### 2.2 查询模板详情

### `GET /api/v1/templates/{template_id}`

**请求示例：**

```bash
curl http://127.0.0.1:8000/api/v1/templates/tpl_20260627132835_bce99ff8
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "template_id": "tpl_20260627132835_bce99ff8",
    "template_name": "templete",
    "source_type": "builtin",
    "source_filename": "templete.pptx",
    "slide_count": 48,
    "status": "ready",
    "is_builtin": true,
    "created_at": "2026-06-27T13:28:37",
    "source_ftp_path": "/slides_gen_server/templates/tpl_20260627132835_bce99ff8/source/template.pptx",
    "imported_svg_dir_ftp_path": "/slides_gen_server/templates/tpl_20260627132835_bce99ff8/imported/svg",
    "imported_svg_flat_dir_ftp_path": "/slides_gen_server/templates/tpl_20260627132835_bce99ff8/imported/svg-flat",
    "assets_ftp_dir_path": "/slides_gen_server/templates/tpl_20260627132835_bce99ff8/imported/assets",
    "manifest_ftp_path": "/slides_gen_server/templates/tpl_20260627132835_bce99ff8/manifest/template_manifest.json"
  }
}
```

### 2.3 导入私有模板

### `POST /api/v1/templates/import`

上传 PPTX 文件作为私有模板。需要鉴权。

**请求格式：** `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `template_name` | string | 是 | 模板名称 |
| `template_file` | file | 是 | PPTX 文件 |

**请求示例：**

```bash
curl -X POST http://127.0.0.1:8000/api/v1/templates/import \
  -H "X-LLM-API-Key: your-api-key" \
  -F "template_name=我的模板" \
  -F "template_file=@my_template.pptx"
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "template_id": "tpl_20260627140000_abc12345",
    "template_name": "我的模板",
    "slide_count": 20,
    "status": "ready"
  }
}
```

### 2.4 导入公共模板

### `POST /api/v1/templates/import-builtin`

导入公共基础模板。无需鉴权。

**请求格式：** `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `template_name` | string | 否 | 模板名称，不传则使用文件名 |
| `template_file` | file | 否 | PPTX 文件，不传则使用默认模板 |

**请求示例：**

```bash
curl -X POST http://127.0.0.1:8000/api/v1/templates/import-builtin \
  -F "template_name=基础模板" \
  -F "template_file=@base.pptx"
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "template_id": "tpl_20260627140000_abc12345",
    "template_name": "基础模板",
    "slide_count": 48,
    "status": "ready"
  }
}
```

---

## 3. 任务管理

### 3.1 创建旧模式生成任务【已实现】

### `POST /api/v1/tasks`

提交 `legacy_hybrid` 旧模式 PPT 生成任务，异步执行。未传新模式时继续保留该行为。分离生成模式前端请使用第 4 节的 `/generations` 接口。需要鉴权。

**请求体（JSON）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `requirement_text` | string | 是 | PPT 生成需求全文 |
| `template_id` | string \| null | 否 | 模板 ID，为空使用默认模板 |
| `task_id` | string \| null | 否 | 自定义任务 ID，为空自动生成 |
| `custom_requirements` | string \| null | 否 | 用户自定义的额外要求，将注入到每页的规划和生成提示词中 |
| `options` | object | 否 | 任务执行参数 |

**`options` 子字段：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `output_filename` | string \| null | null | 最终输出文件名建议 |
| `model` | string \| null | null | LLM 模型名称，为空用环境变量默认值 |
| `enable_thinking` | bool | false | 是否启用模型思考模式 |
| `keep_artifacts` | bool \| null | null | 是否保留中间产物到 FTP |
| `max_page_concurrency` | int \| null | null | 单任务分页最大并发数 |

**请求示例：**

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks \
  -H "X-LLM-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "requirement_text": "请生成一份关于信息披露优化项目的方案PPT，内容包括需求背景、需求概述、项目方案要点、实施计划等。",
    "template_id": null,
    "custom_requirements": "每页内容不超过5个要点，使用简洁的商业语言",
    "options": {
      "output_filename": "信息披露优化方案.pptx",
      "model": "deepseek-v4-flash",
      "enable_thinking": false
    }
  }'
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "task_id": "task_20260703160147_7358a679",
    "status": "pending",
    "current_stage": "queued",
    "progress": 0,
    "template_id": "tpl_20260627132835_bce99ff8",
    "ftp_result_pptx_path": null,
    "error_message": null,
    "created_at": "2026-07-03T16:01:47",
    "completed_at": null
  }
}
```

### 3.2 查询任务列表

### `GET /api/v1/tasks`

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `status` | string | null | 按状态过滤 |
| `offset` | int | 0 | 分页偏移 |
| `limit` | int | 20 | 每页数量 |
| `ids_only` | bool | false | 仅返回任务 ID 列表 |

**状态可选值：** `pending` / `running` / `stopping` / `stopped` / `resuming` / `completed` / `failed` / `cancelled`

**请求示例：**

```bash
curl http://127.0.0.1:8000/api/v1/tasks?status=completed&limit=5 \
  -H "X-LLM-API-Key: your-api-key"
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "task_id": "task_20260703160147_7358a679",
      "status": "completed",
      "current_stage": "completed",
      "progress": 100,
      "template_id": "tpl_20260627132835_bce99ff8",
      "ftp_result_pptx_path": "/slides_gen_server/tasks/task_20260703160147_7358a679/result/result.pptx",
      "error_message": null,
      "created_at": "2026-07-03T16:01:47",
      "completed_at": "2026-07-03T16:05:10"
    }
  ]
}
```

### 3.3 查询任务详情

### `GET /api/v1/tasks/{task_id}`

**请求示例：**

```bash
curl http://127.0.0.1:8000/api/v1/tasks/task_20260703160147_7358a679 \
  -H "X-LLM-API-Key: your-api-key"
```

**响应示例（运行中）：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "task_id": "task_20260703160147_7358a679",
    "status": "running",
    "current_stage": "page_generation",
    "progress": 45.83,
    "template_id": "tpl_20260627132835_bce99ff8",
    "ftp_result_pptx_path": null,
    "error_message": null,
    "created_at": "2026-07-03T16:01:47",
    "completed_at": null
  }
}
```

**`current_stage` 可选值：**

| 阶段 | 说明 |
|------|------|
| `queued` | 任务已入队，等待执行 |
| `preparing` | 准备阶段：加载模板、复制 SVG、解析规则 |
| `page_generation` | 并发逐页生成中 |
| `exporting` | 混合导出 PPTX 中 |
| `completed` | 任务完成 |
| `failed` | 任务失败 |
| `stop_requested` | 已收到停止请求 |
| `stopped` | 已停止 |

### 3.4 查询分页状态

### `GET /api/v1/tasks/{task_id}/pages`

返回每一页的规划与生成状态。

**请求示例：**

```bash
curl http://127.0.0.1:8000/api/v1/tasks/task_20260703160147_7358a679/pages \
  -H "X-LLM-API-Key: your-api-key"
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "task_id": "task_20260703160147_7358a679",
      "page_no": 1,
      "page_name": "封面",
      "should_generate": true,
      "skip_reason": null,
      "status": "completed",
      "diagram_kind": null,
      "ftp_generated_svg_path": null,
      "ftp_final_svg_path": null,
      "error_message": null
    },
    {
      "task_id": "task_20260703160147_7358a679",
      "page_no": 15,
      "page_name": "slide_15",
      "should_generate": true,
      "skip_reason": null,
      "status": "completed",
      "diagram_kind": null,
      "ftp_generated_svg_path": "/slides_gen_server/tasks/task_20260703160147_7358a679/svg_output/slide_15.svg",
      "ftp_final_svg_path": "/slides_gen_server/tasks/task_20260703160147_7358a679/svg_final/slide_15.svg",
      "error_message": null
    },
    {
      "task_id": "task_20260703160147_7358a679",
      "page_no": 22,
      "page_name": "应用架构",
      "should_generate": false,
      "skip_reason": "模板要求描述应用架构，但需求文本中未提供具体的架构内容",
      "status": "skipped",
      "diagram_kind": null,
      "ftp_generated_svg_path": null,
      "ftp_final_svg_path": null,
      "error_message": null
    }
  ]
}
```

**`status` 可选值：** `pending` / `running` / `completed` / `skipped` / `failed`

> 当前代码中的 `page_name` 通常是 `slide_15` 这类模板 SVG 文件名，`diagram_kind` 尚未由业务逻辑写入。新模式前端不要依赖这两个旧字段识别图形，应使用第4.6节的 `section_title/diagram_title/diagram_kind`。

### 3.5 查询任务事件

### `GET /api/v1/tasks/{task_id}/events`

返回任务执行过程中的事件日志。

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 100 | 最多返回事件数 |

**请求示例：**

```bash
curl http://127.0.0.1:8000/api/v1/tasks/task_20260703160147_7358a679/events?limit=10 \
  -H "X-LLM-API-Key: your-api-key"
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "event_id": "evt_001",
      "task_id": "task_20260703160147_7358a679",
      "page_no": null,
      "event_type": "task_created",
      "event_stage": "queued",
      "event_message": "任务已创建",
      "event_detail": null,
      "created_at": "2026-07-03T16:01:47"
    },
    {
      "event_id": "evt_002",
      "task_id": "task_20260703160147_7358a679",
      "page_no": null,
      "event_type": "planning_done",
      "event_stage": "page_planning",
      "event_message": "页面规划完成，共48页",
      "event_detail": null,
      "created_at": "2026-07-03T16:02:30"
    },
    {
      "event_id": "evt_003",
      "task_id": "task_20260703160147_7358a679",
      "page_no": 22,
      "event_type": "page_skipped",
      "event_stage": "page_generation",
      "event_message": "第 22 页跳过: 模板要求描述应用架构，但需求文本中未提供具体的架构内容",
      "event_detail": null,
      "created_at": "2026-07-03T16:03:13"
    },
    {
      "event_id": "evt_004",
      "task_id": "task_20260703160147_7358a679",
      "page_no": null,
      "event_type": "exported",
      "event_stage": "completed",
      "event_message": "最终 PPTX 已导出",
      "event_detail": null,
      "created_at": "2026-07-03T16:05:10"
    }
  ]
}
```

### 3.6 查询任务产物

### `GET /api/v1/tasks/{task_id}/artifacts`

返回任务产生的所有文件产物列表。

**请求示例：**

```bash
curl http://127.0.0.1:8000/api/v1/tasks/task_20260703160147_7358a679/artifacts \
  -H "X-LLM-API-Key: your-api-key"
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "artifact_id": "art_001",
      "task_id": "task_20260703160147_7358a679",
      "page_no": null,
      "artifact_type": "request_json",
      "ftp_path": "/slides_gen_server/tasks/task_20260703160147_7358a679/request/request.json",
      "file_name": "request.json",
      "is_final": false,
      "status": "ready",
      "created_at": "2026-07-03T16:01:47"
    },
    {
      "artifact_id": "art_002",
      "task_id": "task_20260703160147_7358a679",
      "page_no": null,
      "artifact_type": "analysis_json",
      "ftp_path": "/slides_gen_server/tasks/task_20260703160147_7358a679/analysis/page_plans.json",
      "file_name": "page_plans.json",
      "is_final": false,
      "status": "ready",
      "created_at": "2026-07-03T16:02:30"
    },
    {
      "artifact_id": "art_003",
      "task_id": "task_20260703160147_7358a679",
      "page_no": 15,
      "artifact_type": "svg_final",
      "ftp_path": "/slides_gen_server/tasks/task_20260703160147_7358a679/svg_final/slide_15.svg",
      "file_name": "slide_15.svg",
      "is_final": false,
      "status": "ready",
      "created_at": "2026-07-03T16:03:50"
    },
    {
      "artifact_id": "art_004",
      "task_id": "task_20260703160147_7358a679",
      "page_no": null,
      "artifact_type": "validation_report",
      "ftp_path": "/slides_gen_server/tasks/task_20260703160147_7358a679/validation/validation_report.json",
      "file_name": "validation_report.json",
      "is_final": true,
      "status": "ready",
      "created_at": "2026-07-03T16:05:08"
    },
    {
      "artifact_id": "art_005",
      "task_id": "task_20260703160147_7358a679",
      "page_no": null,
      "artifact_type": "result_pptx",
      "ftp_path": "/slides_gen_server/tasks/task_20260703160147_7358a679/result/result.pptx",
      "file_name": "result.pptx",
      "is_final": true,
      "status": "ready",
      "created_at": "2026-07-03T16:05:10"
    }
  ]
}
```

**`artifact_type` 可选值：**

| 类型 | 说明 |
|------|------|
| `request_json` | 原始请求 JSON |
| `requirement_md` | 需求文本 Markdown |
| `analysis_json` | 页面规划 JSON / 结构化生成结果 |
| `svg_output` | LLM 原始生成的 SVG |
| `svg_final` | 校验后的最终 SVG |
| `validation_report` | 校验报告 |
| `result_pptx` | 最终 PPTX 文件 |

### 3.7 下载 PPTX

### `GET /api/v1/tasks/{task_id}/download`

下载最终生成的 PPTX 文件。任务必须处于 `completed` 状态。

**请求示例：**

```bash
curl -o result.pptx http://127.0.0.1:8000/api/v1/tasks/task_20260703160147_7358a679/download \
  -H "X-LLM-API-Key: your-api-key"
```

**成功响应：** 返回二进制文件，`Content-Type: application/vnd.openxmlformats-officedocument.presentationml.presentation`

**任务未完成时响应：**

```json
{
  "code": 409,
  "message": "任务尚未完成，暂不可下载",
  "data": null
}
```

### 3.8 停止任务

### `POST /api/v1/tasks/{task_id}/stop`

请求停止正在运行的任务。正在处理的页面会完成当前步骤后停止。

**请求示例：**

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/task_20260703160147_7358a679/stop \
  -H "X-LLM-API-Key: your-api-key"
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "task_id": "task_20260703160147_7358a679",
    "status": "stopping",
    "stop_requested": true,
    "resume_count": 0
  }
}
```

### 3.9 恢复任务

### `POST /api/v1/tasks/{task_id}/resume`

恢复已停止或失败的任务。会重新执行未完成的页面。

**请求示例：**

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/task_20260703160147_7358a679/resume \
  -H "X-LLM-API-Key: your-api-key"
```

**响应示例：**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "task_id": "task_20260703160147_7358a679",
    "status": "resuming",
    "stop_requested": false,
    "resume_count": 1
  }
}
```

---

## 4. 分离生成模式【新增·待实现】

> 本节是已经确认的目标接口契约，供前端预先开发。当前后端代码尚未提供这些接口。

### 4.1 资源与任务关系

```text
GenerationRequest（generation_id）
├─ BodyTask（task_type=body）
├─ DiagramTask（task_type=diagrams，可产生多个 SVG）
└─ ComposeTask（task_type=compose，依赖前两项）
```

- BodyTask 与 DiagramTask 是平级任务，可以独立创建和恢复；
- ComposeTask 是下游任务；
- 只生成 SVG 时 `body_status=not_requested`，不创建正文任务；
- 同一 `generation_id` 后续补齐另一个任务后，`auto_compose=true` 会自动组装；
- 图形部分失败时，成功图形仍参与组装，聚合状态为 `completed_with_warnings`。

### 4.2 枚举值总表

#### 4.2.1 `generation_mode`

| 值 | 说明 |
|---|---|
| `legacy_hybrid` | 旧模式：普通页结构化填充，diagram 页生成整页 SVG |
| `separated_body_diagram` | **【新增】** 正文和单图 SVG 分离生成模式 |

#### 4.2.2 `targets`

| 值 | 说明 |
|---|---|
| `body` | 创建正文 PPT 任务 |
| `diagrams` | 创建独立图形 SVG 任务 |

`targets` 是数组，允许 `["body"]`、`["diagrams"]`、`["body","diagrams"]`，至少包含一项，不允许重复。

#### 4.2.3 `task_type`

| 值 | 说明 |
|---|---|
| `legacy` | 旧模式任务 |
| `body` | 新模式正文任务 |
| `diagrams` | 新模式图形任务 |
| `compose` | 新模式组装任务 |

#### 4.2.4 Generation 聚合状态 `status`

| 值 | 说明 |
|---|---|
| `pending` | 已创建，子任务等待执行 |
| `running` | 至少一个子任务执行中 |
| `completed` | 请求的产物全部成功 |
| `completed_with_warnings` | 有可用结果，但部分图形或非关键步骤失败 |
| `failed` | 没有可用结果，或关键正文/组装步骤失败 |

#### 4.2.5 子任务状态

沿用任务状态并新增告警完成状态：

`pending` / `running` / `stopping` / `stopped` / `resuming` / `completed` / `completed_with_warnings` / `failed` / `cancelled`

#### 4.2.6 聚合子状态

`body_status`、`diagram_status` 可选值：

`not_requested` / `pending` / `running` / `completed` / `completed_with_warnings` / `failed`

`compose_status` 可选值：

`not_requested` / `waiting` / `pending` / `running` / `completed` / `completed_with_warnings` / `failed`

- `not_requested`：没有请求该能力；
- `waiting`：已开启自动组装，但正文或图形前置条件尚未满足。

#### 4.2.7 Diagram 状态与校验状态

- `diagram.status`：`pending` / `running` / `completed` / `failed`
- `validation_status`：`pending` / `passed` / `failed`

#### 4.2.8 新模式 `current_stage`

| task_type | 阶段枚举 |
|---|---|
| `body` | `queued` / `preparing` / `planning` / `page_generation` / `exporting_body` / `completed` / `failed` |
| `diagrams` | `queued` / `preparing` / `planning` / `diagram_generation` / `validating` / `completed` / `completed_with_warnings` / `failed` |
| `compose` | `queued` / `waiting_dependencies` / `composing` / `completed` / `completed_with_warnings` / `failed` |

### 4.3 创建 Generation【新增·待实现】

### `POST /api/v1/generations`

创建一份不可变输入，并按 `targets` 创建正文和/或图形子任务。

#### 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| `generation_mode` | string | 是 | — | 必须为 `separated_body_diagram` |
| `template_id` | string \| null | 否 | null | 为空时使用默认模板 |
| `targets` | string[] | 是 | — | `body`、`diagrams`，至少一个 |
| `auto_compose` | bool | 否 | true | 同一 generation 下正文和图形均可用时自动组装 |
| `requirement_text` | string | 是 | — | 上游合并后的所有文档纯文本，1～100000 字符 |
| `custom_requirements` | string \| null | 否 | null | 当前生成指令；业务优先级最高，但不能要求编造输入外事实 |
| `options` | object \| null | 否 | null | 模型和执行参数，字段见下表 |

#### `options` 字段

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `output_filename` | string \| null | null | 组装 PPT 文件名建议；正文文件使用同名加 `_body` 后缀 |
| `model` | string \| null | null | LLM 模型，为空使用服务默认模型 |
| `enable_thinking` | bool | false | 是否启用模型思考模式 |
| `max_page_concurrency` | int \| null | null | 单个子任务页面/图形最大并发数 |
| `keep_artifacts` | bool \| null | true | 新模式建议始终保留关键中间产物 |

#### `requirement_text` 规则

- 所有文档地位相同，统一放入该字段；
- 50000 字符及以上返回告警，但仍创建；
- 超过 100000 字符返回 HTTP 422，不创建；
- 即使少于 100000 字符，也会检查所选模型上下文容量；
- 禁止静默截断；
- 上游以“文档标题 + 至少20个连续半角横线”表示文档边界；
- 文档边界只帮助模型分段，不产生优先级。

#### 请求示例：同时生成正文、图形并自动组装

```json
{
  "generation_mode": "separated_body_diagram",
  "template_id": "tpl_20260627132835_bce99ff8",
  "targets": ["body", "diagrams"],
  "auto_compose": true,
  "requirement_text": "需求文档\n----------------------------------------\n项目名称：信息披露优化项目……\n\n工作量估算书\n----------------------------------------\n总工作量最终值：120人月……",
  "custom_requirements": "语言简洁，只填写输入中明确提供的信息",
  "options": {
    "output_filename": "信息披露优化方案.pptx",
    "model": "qwen3.6-27b",
    "enable_thinking": false,
    "max_page_concurrency": 4,
    "keep_artifacts": true
  }
}
```

#### 请求示例：只生成 SVG

```json
{
  "generation_mode": "separated_body_diagram",
  "template_id": null,
  "targets": ["diagrams"],
  "auto_compose": true,
  "requirement_text": "项目整体架构图要求\n----------------------------------------\n系统A通过HTTPS调用系统B……",
  "custom_requirements": "架构关系必须与输入一致"
}
```

#### 成功响应示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "generation_id": "gen_20260901103000_a1b2c3d4",
    "generation_mode": "separated_body_diagram",
    "status": "pending",
    "auto_compose": true,
    "requirement_text_chars": 62840,
    "warnings": [
      {
        "code": "REQUIREMENT_TEXT_LARGE",
        "message": "需求文本超过50000字符，生成质量可能下降"
      }
    ],
    "body_task_id": "task_body_20260901103000_1111",
    "diagram_task_id": "task_diagram_20260901103000_2222",
    "compose_task_id": null,
    "body_status": "pending",
    "diagram_status": "pending",
    "compose_status": "waiting",
    "created_at": "2026-09-01T10:30:00"
  }
}
```

#### 只生成 SVG 时的响应差异

```json
{
  "generation_id": "gen_20260901104000_e5f6g7h8",
  "body_task_id": null,
  "diagram_task_id": "task_diagram_20260901104000_3333",
  "compose_task_id": null,
  "body_status": "not_requested",
  "diagram_status": "pending",
  "compose_status": "waiting"
}
```

### 4.4 查询 Generation 列表与聚合状态【新增·待实现】

#### `GET /api/v1/generations`

查询当前 API Key 的输入聚合列表。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `status` | string \| null | null | 按 Generation 聚合状态过滤 |
| `offset` | int | 0 | 分页偏移 |
| `limit` | int | 20 | 每页数量，建议最大100 |
| `ids_only` | bool | false | 是否只返回 generation_id |

响应示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "generation_id": "gen_20260901103000_a1b2c3d4",
      "status": "completed_with_warnings",
      "template_id": "tpl_20260627132835_bce99ff8",
      "body_status": "completed",
      "diagram_status": "completed_with_warnings",
      "compose_status": "completed_with_warnings",
      "requirement_text_chars": 62840,
      "diagram_count": 3,
      "created_at": "2026-09-01T10:30:00",
      "completed_at": "2026-09-01T10:38:20"
    }
  ]
}
```

#### `GET /api/v1/generations/{generation_id}`

返回输入概要、三个任务状态和可下载产物，不返回完整 `requirement_text`。

#### 响应示例：部分图形失败但已完成组装

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "generation_id": "gen_20260901103000_a1b2c3d4",
    "generation_mode": "separated_body_diagram",
    "status": "completed_with_warnings",
    "auto_compose": true,
    "template_id": "tpl_20260627132835_bce99ff8",
    "requirement_text_chars": 62840,
    "warnings": [
      {
        "code": "DIAGRAM_PARTIAL_FAILURE",
        "message": "共规划3个图形，2个成功，1个失败"
      }
    ],
    "body_task_id": "task_body_20260901103000_1111",
    "diagram_task_id": "task_diagram_20260901103000_2222",
    "compose_task_id": "task_compose_20260901103600_4444",
    "body_status": "completed",
    "diagram_status": "completed_with_warnings",
    "compose_status": "completed_with_warnings",
    "kept_page_count": 16,
    "skipped_page_count": 32,
    "diagram_count": 3,
    "diagram_completed_count": 2,
    "diagram_failed_count": 1,
    "artifacts": {
      "body_pptx": {
        "artifact_id": "art_body_001",
        "file_name": "信息披露优化方案_body.pptx",
        "download_url": "/api/v1/tasks/task_body_20260901103000_1111/artifacts/art_body_001/download"
      },
      "composed_pptx": {
        "artifact_id": "art_compose_001",
        "file_name": "信息披露优化方案.pptx",
        "download_url": "/api/v1/tasks/task_compose_20260901103600_4444/artifacts/art_compose_001/download"
      },
      "diagram_manifest": {
        "artifact_id": "art_diagram_manifest_001",
        "download_url": "/api/v1/tasks/task_diagram_20260901103000_2222/artifacts/art_diagram_manifest_001/download"
      }
    },
    "created_at": "2026-09-01T10:30:00",
    "completed_at": "2026-09-01T10:38:20"
  }
}
```

#### 聚合状态规则

- 只请求一种目标且该任务成功：`completed`；
- 正文成功、部分图形失败且已完成部分组装：`completed_with_warnings`；
- 图形全部失败但正文成功：`completed_with_warnings`，不创建 compose 产物；
- 所有请求的目标均失败：`failed`；
- `compose_status=waiting` 不阻止只请求 SVG 的 generation 在图形完成后变为 `completed`。

### 4.5 后续补触发子任务【新增·待实现】

### `POST /api/v1/generations/{generation_id}/tasks`

用于在同一输入下补生成正文或图形，不需要再次发送 `requirement_text`。

#### 请求字段

| 字段 | 类型 | 必填 | 枚举 |
|---|---|---:|---|
| `task_type` | string | 是 | `body` / `diagrams` |

#### 请求示例

```json
{
  "task_type": "body"
}
```

#### 响应示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "generation_id": "gen_20260901104000_e5f6g7h8",
    "task_id": "task_body_20260901120000_5555",
    "task_type": "body",
    "status": "pending",
    "compose_status": "waiting"
  }
}
```

#### 状态限制

- 对应任务为 `not_requested`：创建新任务；
- 对应任务为 `pending/running/resuming`：返回 409；
- 对应任务为 `failed`：不新建任务，前端应调用原任务 `/resume`；
- 对应任务为 `completed/completed_with_warnings`：返回 409，防止覆盖成功产物；
- 两类任务完成后，若 `auto_compose=true`，自动创建 ComposeTask。

### 4.6 查询图形列表【新增·待实现】

### `GET /api/v1/generations/{generation_id}/diagrams`

返回该输入下 DiagramTask 产生的全部图形。SVG-only 场景的 `final_page_no` 为 `null`，前端不展示页码。

#### 图形字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `diagram_id` | string | 图形唯一 ID |
| `task_id` | string | 所属 DiagramTask ID |
| `status` | string | `pending/running/completed/failed` |
| `diagram_title` | string | 图形标题 |
| `section_title` | string | 所属模板章节标题 |
| `diagram_kind` | string | 自由文本图形类型，不限制枚举，如架构图、流程图、时序图、部署图 |
| `diagram_description` | string | 图形内容说明 |
| `final_page_no` | int \| null | 组装后页码；SVG-only 为 null |
| `preview_url` | string \| null | 直接 SVG 预览地址 |
| `download_url` | string \| null | SVG 下载地址 |
| `validation_status` | string | `pending/passed/failed` |
| `error_message` | string \| null | 失败信息 |

#### 响应示例：SVG-only

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "diagram_id": "diagram_001",
      "task_id": "task_diagram_20260901104000_3333",
      "status": "completed",
      "diagram_title": "项目整体系统交互架构图",
      "section_title": "项目整体架构图及说明",
      "diagram_kind": "系统交互架构图",
      "diagram_description": "展示系统A通过HTTPS调用系统B，并通过批量文件连接系统C",
      "final_page_no": null,
      "preview_url": "/api/v1/tasks/task_diagram_20260901104000_3333/diagrams/diagram_001/preview",
      "download_url": "/api/v1/tasks/task_diagram_20260901104000_3333/diagrams/diagram_001/download",
      "validation_status": "passed",
      "error_message": null
    }
  ]
}
```

#### 响应示例：已组装

组装完成后同一图形返回：

```json
{
  "diagram_id": "diagram_001",
  "diagram_title": "项目整体系统交互架构图",
  "section_title": "项目整体架构图及说明",
  "final_page_no": 8,
  "status": "completed",
  "validation_status": "passed"
}
```

### 4.7 查询单个图形详情【新增·待实现】

### `GET /api/v1/tasks/{task_id}/diagrams/{diagram_id}`

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "diagram_id": "diagram_001",
    "generation_id": "gen_20260901104000_e5f6g7h8",
    "task_id": "task_diagram_20260901104000_3333",
    "status": "completed",
    "diagram_title": "项目整体系统交互架构图",
    "section_title": "项目整体架构图及说明",
    "diagram_kind": "系统交互架构图",
    "diagram_description": "展示系统A、系统B和系统C的连接关系",
    "final_page_no": null,
    "evidence_quotes": [
      "系统A通过HTTPS调用系统B",
      "系统B每日通过批量文件向系统C同步数据"
    ],
    "applied_check_rule_ids": ["rule_011"],
    "applied_global_rule_ids": ["global_page_rule_001"],
    "validation_status": "passed",
    "layout_decision": null,
    "preview_url": "/api/v1/tasks/task_diagram_20260901104000_3333/diagrams/diagram_001/preview",
    "download_url": "/api/v1/tasks/task_diagram_20260901104000_3333/diagrams/diagram_001/download",
    "error_message": null
  }
}
```

### 4.8 直接预览 SVG【新增·待实现】

### `GET /api/v1/tasks/{task_id}/diagrams/{diagram_id}/preview`

成功时直接返回经过安全净化的 SVG 内容，不使用统一 JSON 包装：

```http
HTTP/1.1 200 OK
Content-Type: image/svg+xml; charset=utf-8
Content-Disposition: inline; filename="diagram_001.svg"
Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src data:
X-Content-Type-Options: nosniff
```

安全要求：删除 `script`、事件属性、`foreignObject`、外部 URL、外部字体和不受控引用。前端应使用隔离的 `object/iframe` 或安全图片容器展示，不把未经处理的 SVG 字符串直接写入高权限 DOM。

### 4.9 下载 SVG【新增·待实现】

### `GET /api/v1/tasks/{task_id}/diagrams/{diagram_id}/download`

返回净化并通过校验的最终 SVG：

```http
Content-Type: image/svg+xml
Content-Disposition: attachment; filename="项目整体系统交互架构图.svg"
```

### 4.10 任务查询新增字段【新增·待实现】

现有 `GET /api/v1/tasks` 和 `GET /api/v1/tasks/{task_id}` 在保持原字段的基础上增加。

`GET /api/v1/tasks` 新增可选查询参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| **`generation_id`** | string \| null | **【新增】只查询指定 Generation 的子任务** |
| **`task_type`** | string \| null | **【新增】按 `legacy/body/diagrams/compose` 过滤** |

响应新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `generation_id` | string \| null | 新模式父输入 ID；旧任务为 null |
| `task_type` | string | `legacy/body/diagrams/compose` |
| `status` | string | 新增 `completed_with_warnings` |
| `artifact_count` | int | 任务产物数量 |
| `error_message` | string \| null | 当前任务错误 |

#### 子任务详情示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "task_id": "task_diagram_20260901103000_2222",
    "generation_id": "gen_20260901103000_a1b2c3d4",
    "task_type": "diagrams",
    "status": "completed_with_warnings",
    "current_stage": "completed_with_warnings",
    "progress": 100,
    "template_id": "tpl_20260627132835_bce99ff8",
    "artifact_count": 4,
    "diagram_count": 3,
    "completed_diagram_count": 2,
    "failed_diagram_count": 1,
    "error_message": "1个图形生成失败，可调用resume继续",
    "created_at": "2026-09-01T10:30:00",
    "completed_at": "2026-09-01T10:36:00"
  }
}
```

### 4.11 正文分页状态新增字段【新增·待实现】

`GET /api/v1/tasks/{body_task_id}/pages` 返回最终正文页。新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `page_key` | string | 内部稳定页面标识，前端只需作为 key 使用 |
| `template_page_no` | int | 原模板页码 |
| `page_no` | int | 当前正文/组装 PPT 的最终页码 |
| `section_title` | string | 固定章节标题 |
| `information_sufficient` | bool | 输入是否足以生成该页 |
| `evidence_quotes` | string[] | requirement_text 原文依据摘录 |
| `diagram_required` | bool | 本章节是否需要图形 |
| `should_generate` | bool | 是否保留该页 |
| `skip_reason` | string \| null | 删除原因 |
| `status` | string | `pending/running/completed/skipped/failed` |

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "task_id": "task_body_20260901103000_1111",
      "page_key": "tpl_20260627132835_bce99ff8:15",
      "template_page_no": 15,
      "page_no": 8,
      "section_title": "项目整体架构图及说明",
      "information_sufficient": true,
      "evidence_quotes": ["系统A通过HTTPS调用系统B"],
      "diagram_required": true,
      "should_generate": true,
      "skip_reason": null,
      "status": "completed",
      "error_message": null
    }
  ]
}
```

### 4.12 产物类型枚举【新增项突出】

| artifact_type | 状态 | 说明 |
|---|---|---|
| `request_json` | 已有 | 原始请求快照 |
| `requirement_md` | 已有 | 需求文本快照 |
| `analysis_json` | 已有 | 分析结果 |
| `structured_result` | 已有 | 结构化正文页结果 |
| `svg_output` | 已有 | 旧模式原始整页 SVG |
| `svg_final` | 已有 | 旧模式最终整页 SVG |
| `validation_report` | 已有 | 校验报告 |
| `result_pptx` | 已有 | 旧模式最终 PPTX |
| **`planning_manifest`** | **新增** | Generation 共享规划结果 |
| **`page_manifest`** | **新增** | 模板页到最终正文页映射 |
| **`body_pptx`** | **新增** | 未组装正文 PPTX |
| **`diagram_svg`** | **新增** | 单个图形最终 SVG |
| **`diagram_manifest`** | **新增** | 图形清单 JSON |
| **`composed_pptx`** | **新增** | 自动组装后的 PPTX |

产物状态枚举：`ready` / `deleted` / `expired`。本期产物不自动过期，正常情况下均为 `ready`。

### 4.13 精确下载产物【新增·待实现】

### `GET /api/v1/tasks/{task_id}/artifacts/{artifact_id}/download`

- 根据 artifact 的 `content_type` 返回文件；
- 校验 artifact 必须属于当前 API Key 的 task；
- 正文 PPT、组装 PPT、manifest 均通过该接口精确下载；
- 原 `GET /tasks/{task_id}/download` 继续用于旧模式或当前 task 的默认 PPT 产物。

### 4.14 失败任务继续执行【扩展·待实现】

继续复用：

### `POST /api/v1/tasks/{task_id}/resume`

新模式语义：

- `body`：只重做失败/缺失正文页；
- `diagrams`：只重做失败图形；
- `compose`：重新执行本地组装；
- 已成功结果从 FTP 恢复，不重复调用模型；
- `completed_with_warnings` 且存在失败图形的 diagrams task 允许 resume；
- 恢复成功后自动重新判断 compose 依赖。


## 5. 错误响应

### 鉴权失败（401）

```json
{
  "detail": "缺少请求头 X-LLM-API-Key"
}
```

### 资源不存在（404）

```json
{
  "detail": "任务不存在: task_xxx"
}
```

### 状态冲突（409）

```json
{
  "detail": "当前状态不允许停止: completed"
}
```

### 服务未初始化（500）

```json
{
  "detail": "服务尚未完成初始化"
}
```

### requirement_text 超过10万字【新增·422】

```json
{
  "code": 422,
  "message": "requirement_text 超过100000字符上限",
  "data": {
    "actual_chars": 108320,
    "max_chars": 100000
  }
}
```

### 模型上下文不足【新增·422】

```json
{
  "code": 422,
  "message": "所选模型上下文不足以容纳当前输入",
  "data": {
    "model": "model-name",
    "estimated_tokens": 82000,
    "context_limit": 65536
  }
}
```

### 子任务已存在或正在执行【新增·409】

```json
{
  "code": 409,
  "message": "该 generation 的 body 任务已存在",
  "data": {
    "generation_id": "gen_xxx",
    "task_id": "task_body_xxx",
    "status": "running"
  }
}
```

### 图形尚未完成【新增·409】

```json
{
  "code": 409,
  "message": "图形尚未完成，暂不可预览或下载",
  "data": {
    "diagram_id": "diagram_001",
    "status": "running"
  }
}
```

---

## 6. 完整调用流程示例

### 6.1 旧模式【已实现】

```bash
# 1. 检查服务状态
curl http://127.0.0.1:8000/api/v1/health

# 2. 查看可用模板
curl http://127.0.0.1:8000/api/v1/templates

# 3. 创建生成任务
curl -X POST http://127.0.0.1:8000/api/v1/tasks \
  -H "X-LLM-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "requirement_text": "请生成一份关于信息披露优化项目的方案PPT",
    "custom_requirements": "每页内容不超过5个要点，使用简洁的商业语言",
    "options": {
      "output_filename": "信息披露优化方案.pptx",
      "enable_thinking": false
    }
  }'
# 返回 task_id，例如: task_20260703160147_7358a679

# 4. 轮询任务进度
curl http://127.0.0.1:8000/api/v1/tasks/task_20260703160147_7358a679 \
  -H "X-LLM-API-Key: your-api-key"

# 5. 查看分页详情
curl http://127.0.0.1:8000/api/v1/tasks/task_20260703160147_7358a679/pages \
  -H "X-LLM-API-Key: your-api-key"

# 6. 查看事件日志
curl http://127.0.0.1:8000/api/v1/tasks/task_20260703160147_7358a679/events \
  -H "X-LLM-API-Key: your-api-key"

# 7. 下载最终 PPTX（任务完成后）
curl -o result.pptx \
  http://127.0.0.1:8000/api/v1/tasks/task_20260703160147_7358a679/download \
  -H "X-LLM-API-Key: your-api-key"
```

### 6.2 新模式前端调用顺序【新增·待实现】

```text
1. GET  /templates
   → 用户选择模板

2. POST /generations
   → 发送 requirement_text、targets、auto_compose
   → 保存 generation_id、body_task_id、diagram_task_id

3. GET /generations/{generation_id}
   → 轮询聚合状态
   → 分别展示正文、图形、组装状态

4. GET /generations/{generation_id}/diagrams
   → 图形任务有结果后展示 SVG 卡片
   → SVG-only 时只显示图形标题、章节和类型，不显示页码

5. GET /tasks/{diagram_task_id}/diagrams/{diagram_id}/preview
   → 在隔离容器中直接预览 SVG

6. 如果初始只生成 SVG，用户后来点击“生成PPT正文”：
   POST /generations/{generation_id}/tasks
   {"task_type":"body"}
   → 正文成功后后端自动创建 ComposeTask

7. GET /generations/{generation_id}
   → 从 artifacts 获取三个独立下载入口：
      body_pptx / diagram_svg / composed_pptx

8. 子任务失败或部分图形失败：
   POST /tasks/{task_id}/resume
   → 只继续失败部分
```

### 6.3 前端展示建议

- Generation 列表作为一级记录，Task 作为展开后的执行详情；
- 分别显示 `body_status`、`diagram_status`、`compose_status`；
- `completed_with_warnings` 使用警告状态，但正文和成功 SVG 仍允许下载；
- 5万字告警不阻止提交，10万字错误必须阻止提交；
- 前端可以先按本文档开发 Mock 数据，但调用【新增·待实现】接口前应配置功能开关；
- 所有 URL 字段都当作相对 API 地址处理，不直接拼接 FTP 路径。
