# API 接口文档

> 基础路径：`/api/v1`
> 所有接口（除健康检查和模板列表外）需在请求头中携带 `X-LLM-API-Key`。
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

### 3.1 创建生成任务

### `POST /api/v1/tasks`

提交 PPT 生成任务，异步执行。需要鉴权。

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
      "page_name": "系统架构图",
      "should_generate": true,
      "skip_reason": null,
      "status": "completed",
      "diagram_kind": "architecture",
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
      "status": "uploaded",
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
      "status": "uploaded",
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
      "status": "uploaded",
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
      "status": "uploaded",
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
      "status": "uploaded",
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

## 4. 错误响应

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

---

## 5. 完整调用流程示例

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
