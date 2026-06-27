# slides_gen_server

## 简介

这是一个用于生成 PPT 的 FastAPI 服务。

你可以：

- 导入公共基础模板
- 导入你自己的私有模板
- 提交生成任务
- 查询任务进度
- 下载最终 PPTX

## 目录说明

- `templete.pptx`：默认基础模板文件
- `mock_ftp/`：本地模拟 FTP 目录，所有上传产物都可以在这里查看
- `runtime/`：服务运行时工作区
- `docs/`：设计文档和开发说明

如果你想看开发实现细节，请查看：

- `docs/development_notes.md`
- `docs/fastapi_service_architecture.md`
- `docs/mysql_ftp_persistence_design_v2.md`

## 环境要求

- Python 3.10 及以上
- MySQL

远程 FTP 是可选的：

- 本地调试时，不配置 `FTP_HOST` 也可以运行
- 服务会自动使用 `mock_ftp/` 作为本地模拟 FTP

## 基本配置

项目会优先读取根目录的 `.env`。

常用配置项：

- `APP_NAME`
- `API_PREFIX`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`
- `FTP_HOST`
- `FTP_PORT`
- `FTP_USER`
- `FTP_PASSWORD`
- `FTP_ROOT_DIR`
- `MOCK_FTP_DIR`
- `DEFAULT_TEMPLATE_FILE`
- `DEFAULT_TEMPLATE_ID`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_TIMEOUT_SECONDS`

建议：

- 本地调试时保留 `DEFAULT_TEMPLATE_FILE=templete.pptx`
- 如果暂时不想接真实 FTP，就不要配置 `FTP_HOST`

## 安装依赖

如果你使用虚拟环境：

```bash
python -m venv .venv
```

Windows 激活虚拟环境：

```bash
.venv\Scripts\activate
```

安装依赖：

```bash
pip install -e .
```

## 启动服务

在项目根目录执行：

```bash
python -m uvicorn app.main:app --reload
```

或者：

```bash
python -m uvicorn main:app --reload
```

启动后默认访问：

```text
http://127.0.0.1:8000
```

## 健康检查

接口：

```text
GET /api/v1/health
```

返回里会包含：

- `database`：数据库是否可用
- `ftp`：存储层是否可用
- `ftp_mode`：当前是 `mock_only` 还是 `remote+mock`
- `mock_ftp_dir`：本地模拟 FTP 目录

## 模板使用说明

### 1. 导入私有模板

接口：

```text
POST /api/v1/templates/import
```

请求头：

```text
X-LLM-API-Key: 你的 API Key
```

表单参数：

- `template_name`
- `template_file`

说明：

- 这个接口用于导入**当前调用方自己的模板**
- 导入后的模板只有同一个 `X-LLM-API-Key` 才能使用

### 2. 导入公共基础模板

接口：

```text
POST /api/v1/templates/import-builtin
```

这个接口**不需要** `X-LLM-API-Key`。

你有两种用法：

- 不传文件：直接导入或复用根目录的 `templete.pptx`
- 传 `template_file`：把上传的模板导入成所有人可用的公共模板

可选表单参数：

- `template_name`
- `template_file`

说明：

- 这个接口用于导入**所有人都可使用的基础模板**
- 导入后的模板会作为 `is_builtin=1` 的公共模板存在

### 3. 查询模板

接口：

```text
GET /api/v1/templates
GET /api/v1/templates/{template_id}
```

说明：

- 不带 `X-LLM-API-Key` 时，可以看到公共基础模板
- 带 `X-LLM-API-Key` 时，还可以看到你自己的私有模板

## 创建任务

接口：

```text
POST /api/v1/tasks
```

请求头：

```text
X-LLM-API-Key: 你的 API Key
```

请求体示例：

```json
{
  "requirement_text": "请生成一份介绍智能制造平台方案的 PPT",
  "template_id": null,
  "options": {
    "output_filename": "demo.pptx"
  }
}
```

说明：

- `template_id` 可不传
- 不传时，服务会自动使用默认基础模板

## 查询任务

接口：

```text
GET /api/v1/tasks
GET /api/v1/tasks/{task_id}
GET /api/v1/tasks/{task_id}/pages
GET /api/v1/tasks/{task_id}/events
GET /api/v1/tasks/{task_id}/artifacts
```

## 停止与恢复任务

接口：

```text
POST /api/v1/tasks/{task_id}/stop
POST /api/v1/tasks/{task_id}/resume
```

## 下载结果

接口：

```text
GET /api/v1/tasks/{task_id}/download
```

只有当任务状态为 `completed` 时才能下载。

## 本地调试查看产物

无论是否配置真实 FTP，服务都会把产物同步到本地模拟目录。

你可以重点查看：

- `mock_ftp/slides_gen_server/templates/`
- `mock_ftp/slides_gen_server/tasks/`

这里面会有：

- 导入后的模板源文件
- 模板 SVG
- 任务分析 JSON
- 生成后的 SVG
- 最终 PPTX
