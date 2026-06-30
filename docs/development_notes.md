# slides_gen_server 开发说明

## 1. 项目结构

```text
app/
├─ api/v1/endpoints/        接口层（health, tasks, templates）
├─ core/                    配置(config.py)、常量(constants.py)、异常(exceptions.py)
├─ schemas/                 Pydantic 数据模型（task.py, template.py, common.py）
├─ services/                业务编排层
│  ├─ orchestration_service.py    任务全生命周期编排
│  ├─ slide_generation_service.py  逐页规划与生成
│  ├─ task_service.py             任务 CRUD 和状态管理
│  ├─ template_service.py         模板查询与复制
│  ├─ template_import_service.py  模板导入（PPTX→SVG）
│  ├─ svg_validation_service.py   SVG 校验
│  ├─ pptx_export_service.py      SVG→PPTX 导出
│  └─ bootstrap.py                服务依赖组装
├─ infrastructure/
│  ├─ db/                   MySQL 数据库适配
│  ├─ storage/ftp.py        FTP/mock_ftp 存储适配
│  ├─ llm/                  LLM 客户端
│  │  ├─ base.py            抽象接口 + Pydantic 模型
│  │  ├─ openai_like_client.py  OpenAI 风格 API 客户端（httpx2）
│  │  └─ prompt_builder.py  规划和生成 prompt 构建器
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

## 2. 核心生成链路

### 2.1 两阶段逐页生成

每个页面独立走两个阶段：

**阶段一：规划（plan_single_page）**
- 输入：完整需求文本 + 当前页模板 SVG
- LLM 返回 JSON：`should_generate`、`skip_reason`、`page_type`、`page_title`
- 规则：封面/尾页/目录页始终 `should_generate=true`
- 失败处理：重试 3 次，仍失败则回退启发式逻辑

**阶段二：生成（generate_page_svg）**
- 输入：完整需求文本 + 当前页模板 SVG + 规划结果
- LLM 直接输出完整 SVG 代码（非 JSON）
- 失败处理：重试 3 次，仍失败则标记 `decision_source=failed`，该页不输出到最终 PPTX

### 2.2 任务编排流程

```
run_task()
├─ 加载模板，复制 SVG 到任务工作区
├─ 解析 request_payload_json 获取 options.model / options.enable_thinking
├─ 逐页规划 → plan_pages()
├─ 逐页生成 → generate_page_svg()
│  ├─ should_generate=false → 跳过，记录 skip_reason
│  ├─ decision_source=failed → 跳过，记录错误
│  └─ 正常生成 → 写入 svg_output / svg_final
├─ SVG 校验
├─ 导出 PPTX
├─ 上传产物到 FTP
└─ finally: 清理 runtime 任务目录
```

## 3. LLM 客户端

### 3.1 动态模型和思考模式

- 接口 `options.model` 和 `options.enable_thinking` 可动态指定
- 不传时使用 env 默认值（`LLM_MODEL` / `enable_thinking=false`）
- 参数从 `request_payload_json` 中解析，经 `orchestration_service` → `slide_generation_service` → `openai_like_client` 透传

### 3.2 重试机制

- `plan_single_page` 和 `generate_page_svg` 均有 3 次重试
- 重试间隔递增（2s、4s）
- 规划失败回退启发式；生成失败标记为 `failed` 不输出

### 3.3 流式支持

- 使用 `httpx2` 库
- 规划和生成均支持流式返回（`stream=True`）
- SSE 格式解析 `data: {...}` 行

## 4. 存储策略

### 4.1 FTP 存储

- `FTP_HOST` 留空时：仅使用本地 `mock_ftp/`
- `FTP_HOST` 配置时：远程 FTP + 本地 mock_ftp 双写
- `MOCK_FTP_ENABLED=false`：关闭 mock_ftp 写入，仅用远程 FTP

### 4.2 Runtime 清理

- `runtime/tasks/{task_id}/` 在任务完成或失败后自动清理（`shutil.rmtree`）
- 所有产物已上传 FTP，runtime 仅作为运行时工作区

## 5. 模板策略

- 公共模板：`is_builtin=1`，所有调用方可使用
- 私有模板：带 `api_key` 归属，仅限所属调用方
- 默认模板：项目根目录 `templete.pptx`，启动时自动导入
- 模板主表示为 SVG 工作区（`svg/` + `svg-flat/`）

## 6. Prompt 设计要点

### 6.1 规划 Prompt

- 明确要求封面/尾页/目录页 `should_generate=true`
- 要求输出纯 JSON（无 markdown 代码块）
- 判断依据：模板 SVG 文字内容 + 需求文本匹配度

### 6.2 生成 Prompt

- 直接输出完整 SVG，不输出 JSON 或解释
- 排版规则：参考模板 y 坐标、行间距 24-28px、内容不超 viewBox
- **文本框规则**：同一内容区域的多行文字用一个 `<text>` + 多个 `<tspan>` 实现，不要每行单独创建小文本框
- 只有需要区分标题和正文时才使用不同 `<g>` 组

## 7. 图标资源

`app/vendor/ppt_master/templates/icons/` 下的 SVG 图标被以下脚本使用：

- `scripts/svg_finalize/embed_icons.py`：将 `<use data-icon="...">` 替换为实际 SVG
- `scripts/svg_to_pptx/use_expander.py`：转 PPTX 时内存中展开图标引用

**不能移除该目录。**

## 8. 相关文档

- `docs/fastapi_service_architecture.md`：架构设计
- `docs/mysql_ftp_persistence_design_v2.md`：持久化设计
- `sql/mysql_init_v2.sql`：建表脚本
