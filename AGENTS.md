# AGENTS.md —— slides_gen_server 智能体开发约定

> 本文约束 AI 智能体在继续开发本项目时必须遵守的边界、不变量和最佳实践。每次修改前应重读本文件。

---

## 1. 项目定位

`slides_gen_server` 是一个基于 FastAPI 的 PPT 自动生成服务，核心流程为：

```text
导入 PPTX 模板 → LLM 逐页规划 → LLM 生成（结构化 JSON / 单图 SVG / 整页 SVG）
→ 回填/混合导出 PPTX → 上传 FTP → MySQL 保存元数据
```

支持两种生成模式：

- `legacy_hybrid`：旧模式，按页面类型分流为整页 SVG 或结构化填充。
- `separated_body_diagram`：v4 新模式，正文 PPTX、单图 SVG、最终组装 PPTX 三产物独立生成。

---

## 2. 架构与分层职责

```text
app/
├─ api/v1/endpoints/       # FastAPI 路由，只做参数校验和转发
├─ core/                   # Settings、常量、异常、日志
├─ schemas/                # Pydantic v2 模型（请求/响应/业务模型）
├─ services/               # 业务编排与服务实现
├─ infrastructure/         # 基础设施适配
│  ├─ db/                  # MySQL 仓储
│  ├─ storage/             # FTP / mock_ftp
│  ├─ llm/                 # LLM 客户端、并发、prompt、规则匹配
│  └─ ppt_master/          # PPTX↔SVG 适配器、工作区
├─ vendor/ppt_master/      # 内置运行时脚本，一般只读
└─ main.py                 # FastAPI 入口 +  lifespan
```

### 2.1 不变量：分层边界

1. **API 层**只能调用 `app.services` 中的服务，不能直接访问 `infrastructure`。
2. **Services 层**是编排核心，不直接执行 SQL 或网络请求，通过 `infrastructure` 适配器完成。
3. **infrastructure/db/repository.py** 负责 SQL；新增表必须先定义仓储，并在 `app/services/container.py` 注入。
4. **infrastructure/llm/openai_like_client.py** 是唯一真实 LLM 调用入口；新增 LLM 客户端必须继承 `BasePageGenerationClient`。
5. **PPT 转换**依赖 `app/vendor/ppt_master/scripts/` 下的 `pptx_to_svg`、`svg_to_pptx`、`svg_finalize`；脚本目录**不可删除**。

---

## 3. 数据模型不变量

### 3.1 通用响应格式

所有 HTTP 正常返回必须遵循：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

异常由 `app.main` 中的 `app_error_handler` / `unexpected_error_handler` 统一包装为 `ApiResponse`。

### 3.2 状态枚举

不得随意新增/修改状态字符串，必须使用 `app/core/constants.py` 中的常量：

- 任务：`pending/running/completed/failed/stopped/stopping/resuming/cancelled`
- 分页：`pending/running/completed/skipped/failed`
- v4 聚合：`pending/running/completed/completed_with_warnings/failed`
- v4 子能力：`not_requested/waiting/pending/running/completed/completed_with_warnings/failed`
- 页面类型：`cover/toc/content/diagram/end`
- 产物类型：`request_json/requirement_md/svg_output/svg_final/result_pptx/.../body_pptx/composed_pptx/diagram_svg`

### 3.3 数据库迁移

- 不要修改 `sql/mysql_init_v2.sql`（初始化脚本）。
- 新增表或改表必须通过 `sql/mysql_migration_v<数字>.sql` 增量脚本实现。
- 变更后需确保测试夹具 `tests/conftest.py` 中的 `MockMySQLDatabase` 能兼容新 SQL。

---

## 4. LLM 与 Prompt 不变量

### 4.1 LLM 客户端

- 所有 LLM 请求（规划、整页 SVG、单图 SVG、结构化内容）必须走 `OpenAILikePageGenerationClient`。
- `_call_llm` 内已包含全局并发信号量（`app/infrastructure/llm/concurrency.py`）和 429/网络错误退避，调用方不要再自行加锁或重试。
- 新增 LLM 功能必须先在 `BasePageGenerationClient`（`app/infrastructure/llm/base.py`）定义接口，再在 `OpenAILikePageGenerationClient` 实现。

### 4.2 Prompt 输出格式约束

**规划 Prompt**必须要求 LLM 输出纯 JSON，包含：

```json
{
  "should_generate": true,
  "skip_reason": "",
  "page_type": "content",
  "page_title": "..."
}
```

- `cover/toc/end` 页面必须 `should_generate=true`。
- 不能编造模板中没有依据的内容。

**整页 SVG Prompt** 必须要求 LLM：

- 直接输出完整 `<svg>`，不要 markdown、不要代码块。
- 复用模板 `viewBox/width/height`、坐标、颜色、字体。
- 同一内容区域的多行文字必须一个 `<text>` + 多个 `<tspan>`，禁止每行一个小文本框。

**单图 SVG Prompt** 必须要求 LLM：

- 只输出图形本身，不要整页 PPT 模板。
- 背景透明。
- 优先 viewBox `0 0 900 320`（可随 prompt 场景微调）。
- 图形元素用 `rect/line/path/text/tspan/marker` 等基本标签。

**结构化内容 Prompt** 必须要求 LLM：

- 输出纯 JSON，包含 `should_generate`、`skip_reason`、`elements`。
- `elements` 只能为 `text` 或 `table` 类型。

### 4.3 自定义要求（custom_requirements）

- 随 `request_payload_json` 持久化。
- 注入到规划和生成 system prompt / user prompt。
- 但**不可覆盖防编造规则**：当需求文本不足以填写某页时，必须跳过。

---

## 5. v4 分离生成模式不变量

### 5.1 任务层级

```text
GenerationRequest (generation_id)
├─ BodyTask       (task_type=body)     → body.pptx
├─ DiagramsTask   (task_type=diagrams) → 多个独立 diagram_svg
└─ ComposeTask    (task_type=compose)  → composed.pptx
```

- `generation_id` 在创建时冻结 `requirement_text`、模板、参数，不允许执行中修改。
- `BodyTask` 与 `DiagramsTask` 平级，互不争抢资源。
- `ComposeTask` 依赖两者完成；`auto_compose=true` 时由 `GenerationService` 自动触发。

### 5.2 产物与持久化

- Body 产物 artifact_type = `body_pptx`。
- Diagram 产物 artifact_type = `diagram_svg`，并存入 `sg_generation_diagram`。
- Compose 产物 artifact_type = `composed_pptx`。
- 所有产物长期保存在 FTP/mock_ftp，数据库只保存元数据和路径。

### 5.3 图形生成边界

- 每个图形页最多生成一个 SVG。
- 当模板没有 `diagram` 页但 `custom_requirements` 含“图/连接/架构/流程/关系/连线/箭头/拓扑”等关键词时，允许复用第一个可生成的 `content` 页作为 diagram 页。
- 图形 SVG 必须安全净化（`<script>` 等危险元素应在导入/预览层过滤），预览接口直接返回 `image/svg+xml`。

### 5.4 组装边界

- `HybridPptxExporter` 优先回填正文结构化结果。
- v4 图形 SVG 以**插入模式**叠加到正文页，不删除已有 shape；`insert_svg_pages` 参数控制此行为。
- 图形部分失败时，使用成功图形继续组装，状态为 `completed_with_warnings`。

---

## 6. 测试与验证不变量

### 6.1 测试命令

```bash
# 全量测试（任何改动后必须执行并通过）
.venv\Scripts\python.exe -m pytest tests/ --tb=short

# 大模型连通性测试
.venv\Scripts\python.exe -B scripts/test_llm.py
```

### 6.2 测试夹具

- `tests/conftest.py` 提供 `MockMySQLDatabase`、`MockPptxToSvgAdapter`、`MockSvgToPptxAdapter`。
- 新增 `MockPageGenerationClient` 作为无 LLM 时的可控替代；真实 LLM 测试应使用 `scripts/test_llm.py`。
- `client` fixture 默认使用真实 `OpenAILikePageGenerationClient` 但 `llm_base_url` 为空，因此回退启发式；`client_with_mock_llm` 显式使用 mock LLM。

### 6.3 测试原则

- 新增业务逻辑必须配套单元测试或接口测试。
- 涉及 LLM 的功能优先用 monkeypatch/mock 测试返回值，避免真实网络调用拖慢 CI。
- 修改 `get_settings()` 后，测试夹具中必须 `get_settings.cache_clear()`。

---

## 7. 代码风格与通用约定

1. **Python 版本**：`>=3.10`，使用 `from __future__ import annotations`。
2. **类型提示**：鼓励使用，复杂类型用 `| None`、`dict[int, Path]`、`list[dict]`。
3. **配置读取**：通过 `get_settings()`（`@lru_cache`），测试时需 `cache_clear()`。
4. **API_KEY 处理**：`Settings` 类**不包含** `API_KEY` 字段；从请求头 `X-LLM-API-Key` 或 `os.getenv("API_KEY")` / `.env` 读取，严禁硬编码。
5. **HTTP 客户端**：统一使用 `httpx2`，不要再引入 `httpx` 或 `requests`。
6. **SVG 写入/元数据**：使用 `lxml.etree` 而不是 `xml.etree.ElementTree`，避免命名空间被改写成 `ns0:` 前缀。
7. **路径**：统一使用 `pathlib.Path`，避免字符串路径拼接。
8. **日志**：使用 `logging.getLogger(__name__)`，不要 `print` 业务逻辑。

---

## 8. 安全红线

- **禁止**在代码中硬编码、打印或提交任何 API key、数据库密码、FTP 密码。
- **禁止**读取 `.env` 后将其内容写入日志或响应。
- **禁止**修改 `.gitignore` 移除 `.env`。
- SVG 产物直接返回给客户端前需经过净化/白名单校验，防止 XSS。
- 不要执行用户传入的任意 SQL；所有 SQL 通过 repository 参数化。

---

## 9. 开发边界：允许/禁止做的事

### 9.1 允许做的事

- 新增 endpoint：在 `app/api/v1/endpoints/` 新建文件，并在 `app/api/v1/router.py` 注册。
- 新增 schema：在 `app/schemas/` 新建文件，复用 Pydantic v2。
- 新增仓储：在 `app/infrastructure/db/` 新建，并加入 `app/services/container.py` 与 `app/services/bootstrap.py`。
- 新增业务服务：在 `app/services/` 新建，并在 `app/services/bootstrap.py` 组装。
- 新增常量：必须放入 `app/core/constants.py`。
- 新增配置项：在 `app/core/config.py` 的 `Settings` 中定义，并提供环境变量默认值。
- 新增 prompt：在 `app/infrastructure/llm/prompt_builder.py` 或 `structured_prompt_builder.py` 中扩展方法。

### 9.2 禁止做的事

- 不要删除/移动 `app/vendor/ppt_master/` 目录及其子脚本。
- 不要直接修改 `app/core/utils.py` 中全局工具函数而不更新 `tests/test_utils.py`。
- 不要绕过 `BasePageGenerationClient` 直接调用 LLM。
- 不要为 CI 真实调用 LLM；测试使用 mock。
- 不要随意修改 `pyproject.toml` 依赖版本范围；新增依赖需是已发布 ≥7 天的稳定版本，并确认许可证兼容。

---

## 10. 如何新增一个功能（Checklist）

1. 在 `app/schemas/` 定义请求/响应模型。
2. 在 `app/infrastructure/db/` 增加仓储（如涉及数据变更）。
3. 在 `app/services/` 实现业务逻辑。
4. 在 `app/api/v1/endpoints/` 新增路由，在 `app/api/v1/router.py` 注册。
5. 如需 DB 变更，编写 `sql/mysql_migration_v<N>.sql`。
6. 更新 `app/services/container.py` 与 `app/services/bootstrap.py` 的依赖注入。
7. 补充测试：`tests/` 新增或在已有测试文件中扩展。
8. 运行 `.venv\Scripts\python.exe -m pytest tests/ --tb=short` 确保通过。
9. 如改动了 LLM/Prompt，运行 `scripts/test_llm.py` 验证真实模型表现。

---

## 11. 常见陷阱

- `Settings` 是 `dataclass(slots=True)`，创建时务必传全字段；测试夹具中 `make_settings` 是参考模板。
- `get_settings()` 带 lru_cache，测试切换 env 时需 `get_settings.cache_clear()`。
- `slide_generation_service.py` 的 `_apply_metadata` 已从 `xml.etree` 切换到 `lxml`，后续不要再改回。
- `HybridPptxExporter._inject_svg_slide` 默认会删除目标 slide 原有 shape；v4 组装时通过 `insert_svg_pages` 保持正文不删除。
- `MockPageGenerationClient` 的 `plan_single_page` 通过 `requirement_text` + `custom_requirements` 关键词推断 `page_type=diagram`。

---

## 12. 文档状态提示

`docs/` 中的设计文档部分标记了“【待实现】”，但 v4 核心功能已落地。智能体开发时应以**代码、schema、constants、tests**为准，不可仅依赖文档中的“待实现”标记做判断。
