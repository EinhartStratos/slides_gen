# FastAPI 服务架构说明

## 1. 文档目标

本文档描述项目的实际架构实现，包括分层结构、核心流程、模块职责和关键技术决策。

## 2. 技术栈

- **Web 框架**：FastAPI + Uvicorn
- **HTTP 客户端**：httpx2（支持流式 SSE）
- **数据模型**：Pydantic v2
- **数据库**：MySQL（通过 mysql-connector-python）
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

### 3.2 应用服务层

- `orchestration_service.py`：任务全生命周期编排（核心）
- `slide_generation_service.py`：逐页规划和生成调度
- `task_service.py`：任务数据库操作
- `template_service.py`：模板查询和 SVG 复制
- `template_import_service.py`：PPTX→SVG 模板导入
- `svg_validation_service.py`：SVG 语法校验
- `pptx_export_service.py`：SVG→PPTX 导出
- `bootstrap.py`：依赖注入和组装

### 3.3 基础设施层

- `infrastructure/llm/`：LLM 客户端（OpenAI 风格 API）
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
→ 逐页规划（plan_single_page）→ JSON 结果
→ 逐页生成（generate_page_svg）→ SVG 直出
→ SVG 校验
→ 导出 PPTX
→ 上传产物到 FTP
→ 清理 runtime 任务目录
→ 更新任务状态为 completed
```

## 5. 任务状态机

```
pending → running → completed
                   → failed
running → stopping → stopped
stopped → resuming → running
```

阶段（current_stage）：
- `queued` → `preparing` → `page_planning` → `page_generation` → `validating` → `exporting` → `completed`
- 异常时：`failed`

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

### 6.3 动态模型参数

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

### 8.3 查询接口

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

## 9. 数据库表

| 表名 | 说明 |
|------|------|
| `sg_template` | 模板元数据 |
| `sg_generation_task` | 任务主记录 |
| `sg_generation_task_page` | 分页生成状态 |
| `sg_generation_task_artifact` | 产物 FTP 路径 |
| `sg_generation_task_event` | 任务事件日志 |

DDL 文件：`sql/mysql_init_v2.sql`

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
- Prompt 构建器
- 幻灯片生成服务
