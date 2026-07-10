# slides_gen_server

## 简介

基于 FastAPI 的 PPT 自动生成服务。核心流程：将 PPTX 模板转为逐页 SVG → LLM 逐页规划与生成 → 混合导出最终 PPTX。

系统支持两种生成方式：

- **SVG 生成**：LLM 生成 SVG → 转为可编辑 DrawingML 形状，适用于复杂图形页（架构图、流程图等）
- **结构化填充**：LLM 输出结构化 JSON → 直接回填模板原生文本框和表格，适用于文本/表格页，速度快、编辑性好、支持自动拆页

你可以：

- 导入公共基础模板或私有模板
- 提交生成任务（支持自定义 LLM 模型、思考模式开关、自定义要求）
- 查询任务进度和分页状态
- 下载最终 PPTX

## 目录说明

- `templete.pptx`：默认基础模板文件
- `mock_ftp/`：本地模拟 FTP 目录（可通过 `MOCK_FTP_ENABLED` 关闭）
- `runtime/`：服务运行时工作区（任务完成后自动清理）
- `docs/`：开发文档

## 环境要求

- Python 3.10+
- MySQL
- uv（包管理）

## 环境变量配置

项目根目录 `.env` 文件，关键配置项：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `API_KEY` | LLM API Key | — |
| `BASIC_MODEL` | 默认 LLM 模型名称 | — |
| `HOST` | LLM API 地址 | — |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_SCHEMA` | MySQL 连接信息 | localhost:3306 |
| `FTP_HOST` | 远程 FTP 地址（留空则只用 mock_ftp） | — |
| `FTP_PORT` / `FTP_USER` / `FTP_PASSWORD` | FTP 认证 | — |
| `FTP_ROOT_DIR` | FTP 根目录 | /slides_gen_server |
| `MOCK_FTP_ENABLED` | 是否启用本地 mock_ftp 存储 | true |
| `MOCK_FTP_DIR` | mock_ftp 本地路径 | ./mock_ftp |
| `DEFAULT_TEMPLATE_FILE` | 默认模板 PPTX 文件路径 | ./templete.pptx |
| `DEFAULT_TEMPLATE_ID` | 默认模板 ID（留空自动生成） | — |
| `LLM_BASE_URL` | LLM API 基础 URL（同 HOST） | — |
| `LLM_MODEL` | LLM 模型名称（同 BASIC_MODEL） | — |
| `LLM_TIMEOUT_SECONDS` | LLM 请求超时秒数 | 120 |
| `MAX_LLM_CONCURRENCY` | 全局 LLM 请求最大并发数（规划+生成共享） | 8 |
| `LLM_RATE_LIMIT_MAX_RETRIES` | 429/网络错误最大重试次数 | 5 |
| `LLM_RATE_LIMIT_BASE_DELAY` | 退避基准延迟秒数 | 1.0 |
| `LLM_RATE_LIMIT_MAX_DELAY` | 退避最大延迟秒数 | 60.0 |
| `SVG_PAGE_TYPES` | 使用 SVG 生成的页面类型（逗号分隔），其余走结构化填充 | diagram |

## 安装与启动

```bash
# 安装依赖
uv sync

# 启动服务（监听 0.0.0.0，外部可访问）
uv run python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

默认访问：`http://<本机IP>:8000`（本机可用 `http://127.0.0.1:8000`）

## API 接口

> 详细接口文档见 [docs/api_reference.md](docs/api_reference.md)

### 健康检查

```
GET /api/v1/health
```

### 模板管理

```
POST /api/v1/templates/import          # 导入私有模板（需 X-LLM-API-Key）
POST /api/v1/templates/import-builtin   # 导入公共模板
GET  /api/v1/templates                  # 查询模板列表
GET  /api/v1/templates/{template_id}    # 查询模板详情
```

### 任务管理

```
POST /api/v1/tasks                      # 创建生成任务
GET  /api/v1/tasks                      # 查询任务列表
GET  /api/v1/tasks/{task_id}            # 查询任务详情
GET  /api/v1/tasks/{task_id}/pages      # 查询分页状态
GET  /api/v1/tasks/{task_id}/events     # 查询任务事件
GET  /api/v1/tasks/{task_id}/artifacts  # 查询任务产物
POST /api/v1/tasks/{task_id}/stop       # 停止任务
POST /api/v1/tasks/{task_id}/resume     # 恢复任务
GET  /api/v1/tasks/{task_id}/download   # 下载 PPTX
```

### 创建任务请求示例

```json
{
  "requirement_text": "请生成一份介绍智能制造平台方案的 PPT",
  "template_id": null,
  "custom_requirements": "每页内容不超过5个要点，使用简洁的商业语言",
  "options": {
    "output_filename": "demo.pptx",
    "model": "qwen3.6-27b",
    "enable_thinking": false
  }
}
```

**请求字段说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `requirement_text` | string | 是 | PPT 生成需求全文 |
| `template_id` | string \| null | 否 | 模板 ID，为空使用默认模板 |
| `custom_requirements` | string \| null | 否 | 用户自定义的额外要求，将注入到每页的规划和生成提示词中 |
| `options` | object | 否 | 任务执行参数 |

**`options` 字段说明：**

- `output_filename`：最终输出文件名建议
- `model`：LLM 模型名称（不传则使用 env 默认 `LLM_MODEL`）
- `enable_thinking`：是否启用模型思考模式（默认 false）
- `keep_artifacts`：是否保留中间产物到 FTP

> **注意**：并发控制由全局环境变量 `MAX_LLM_CONCURRENCY` 统一管理，所有任务共享一个信号量。

所有请求需带请求头 `X-LLM-API-Key`。

## 本地调试

- 不配置 `FTP_HOST` 时自动使用 `mock_ftp/` 作为本地存储
- 设置 `MOCK_FTP_ENABLED=false` 可关闭 mock_ftp 文件写入
- `runtime/` 中的任务目录在任务完成（或失败）后自动清理
- 产物可在 `mock_ftp/slides_gen_server/tasks/` 中查看

## 测试

```bash
uv run pytest tests/ -x -q
```

## 开发文档

- [开发说明](docs/development_notes.md)
- [API 接口文档](docs/api_reference.md)
- [架构设计](docs/fastapi_service_architecture.md)
- [持久化设计](docs/mysql_ftp_persistence_design_v2.md)
- [并发设计](docs/concurrency_design.md)
- [混合生成设计](docs/hybrid_generation_design.md)
- [检查规则注入方案](docs/check_rules_injection_design.md)
- [问题修复记录](docs/bugfix_log.md)
