# slides_gen_server

## 简介

基于 FastAPI 的 PPT 自动生成服务。核心流程：将 PPTX 模板转为逐页 SVG → LLM 逐页规划与生成 → 混合导出最终 PPTX。

系统支持两种生成方式：

- **SVG 生成**：LLM 生成 SVG → 转为可编辑 DrawingML 形状，适用于复杂图形页（架构图、流程图等）
- **结构化填充**：LLM 输出结构化 JSON → 直接回填模板原生文本框和表格，适用于文本/表格页，速度快、编辑性好、支持自动拆页

你可以：

- 导入公共基础模板或私有模板
- 提交生成任务（支持自定义 LLM 模型和思考模式开关）
- 查询任务进度和分页状态
- 下载最终 PPTX

## 目录说明

- `templete.pptx`：默认基础模板文件
- `mock_ftp/`：本地模拟 FTP 目录（可通过 `MOCK_FTP_ENABLED` 关闭）
- `runtime/`：服务运行时工作区（任务完成后自动清理）
- `app/vendor/ppt_master/`：内置的 PPTX↔SVG 转换引擎及图标资源
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

# 启动服务
uv run python -m uvicorn app.main:app --reload
```

默认访问：`http://127.0.0.1:8000`

## 核心生成流程

```
1. 创建任务 → 持久化到 MySQL
2. 加载模板 → 复制模板 SVG 到任务工作区 → 解析模板规则（TemplateRuleParser）
3. 并发逐页处理（ThreadPoolExecutor + 全局信号量控制）
   ├─ 规划（LLM）→ 判断 should_generate / page_type / page_title
   │  - 封面、尾页、目录页始终生成
   │  - 无关页面跳过并记录 skip_reason
   │  - LLM 失败自动重试 3 次
   ├─ 按页面类型分流生成
   │  ├─ SVG 路径（diagram 类型）
   │  │  - LLM 生成 SVG → 校验 → 保存到 svg_final/
   │  │  - 转为可编辑 DrawingML 形状（不渲染 PNG）
   │  └─ 结构化路径（cover/toc/content/end 类型）
   │     - LLM 输出结构化 JSON（文本/表格）
   │     - 保存到 structured_results/
   │     - 支持内容溢出自动拆页
   - 全局信号量限制所有任务 LLM 请求总并发数（MAX_LLM_CONCURRENCY）
   - 429 限流自动退避：优先读 Retry-After，无则指数退避+随机抖动
   - 网络错误自动退避重试
4. 混合导出 PPTX
   ├─ 以模板 PPTX 为基础
   ├─ 结构化页面 → PPTBuilder 回填原生文本框/表格
   ├─ SVG 页面 → convert_svg_to_slide_shapes 注入 DrawingML 可编辑形状
   ├─ 删除跳过的页面 → 重排 slide 顺序
   └─ 保存最终 PPTX
5. 上传产物到 FTP → 清理 runtime 任务目录
```

## API 接口

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
  "options": {
    "output_filename": "demo.pptx",
    "model": "qwen3.6-27b",
    "enable_thinking": false
  }
}
```

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
- [架构设计](docs/fastapi_service_architecture.md)
- [持久化设计](docs/mysql_ftp_persistence_design_v2.md)
- [并发设计](docs/concurrency_design.md)
- [混合生成设计](docs/hybrid_generation_design.md)
