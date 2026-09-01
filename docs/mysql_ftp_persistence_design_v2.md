# MySQL 持久化、FTP 存储与任务控制设计 V4

> 更新日期：2026-09-01
>
> **状态说明**：现有5张表和旧任务路径已经实现；`sg_generation_request`、`sg_generation_diagram`、新字段和新 FTP 路径均为分离生成模式的已确认目标，尚待代码和增量迁移实现。

## 1. 文档目标

本文档统一记录当前持久化方式与 v4 分离生成目标：

- 不再引入 `user_id`
- 不再对 `api_key` 做哈希存储或加密存储
- 所有业务表直接使用明文 `api_key`
- 不再使用 `job_id`、`conversation_id`
- `generation_id` 表示一份不可变输入，`task_id` 表示一次具体执行任务
- 一个 `generation_id` 可关联平级的 BodyTask/DiagramTask，以及依赖性的 ComposeTask

本 v4 文档与 [分离生成计划](ppt_body_diagram_separated_generation_plan.md) 共同指导下一步实现。

## 2. 最终设计结论

本轮最新口径如下：

- **Generation 输入、任务、分页、图形 metadata 存 MySQL**
- **正文 PPT、独立 SVG、组装 PPT 和 manifest 存 FTP**
- **数据库只存文本输入、元数据、状态、统计和 FTP 路径**
- **SVG 不存数据库大字段，统一存 FTP**
- **系统通过请求中的明文 `api_key` 识别调用方**
- **不单独设计用户表和 API Key 表**
- **`generation_id` 是输入聚合主键，`task_id` 是执行任务主键**
- **BodyTask 与 DiagramTask 平级，ComposeTask 依赖两者**
- **本期不新增停止能力，保留旧接口兼容**
- **失败任务必须支持检查点续跑，只重做失败部分**
- **所有 FTP 产物不设有效期**
- **必须支持按当前 `api_key` 查询 Generation 和 Task**

## 3. 为什么 SVG 仍然存 FTP

即使现在把调用方识别简化为明文 `api_key`，SVG 的存储策略仍然不变。

结论：

- **不要把 SVG 放进数据库大字段**
- **把 SVG 文件统一存 FTP**

原因：

- 一个任务会产生很多分页 SVG
- SVG 更适合文件级排查、下载和二次处理
- 任务恢复时更容易复用已有分页产物
- 数据库存储大文本不利于查询和维护

## 4. MySQL 与 FTP 的职责划分

## 4.1 MySQL 负责什么

MySQL 负责保存：

- 模板记录
- 模板与旧模式任务记录
- **【待实现】GenerationRequest 不可变输入和聚合状态**
- **【待实现】BodyTask/DiagramTask/ComposeTask 关联与状态**
- 分页生成状态和 requirement_text 证据摘录
- **【待实现】独立图形 metadata、校验结果和最终页码**
- 任务事件日志和各类产物 FTP 路径
- 恢复相关状态
- 调用方对应的明文 `api_key`

## 4.2 FTP 负责什么

FTP 负责保存：

- 用户上传的模板 PPTX
- 模板导入后的 SVG 工作区
- 旧模式的 `svg_output/` 和 `svg_final/`
- **【待实现】Generation 请求快照、requirement_text 和 planning manifest**
- **【待实现】未组装正文 PPTX 和 page manifest**
- **【待实现】每个独立图形的最终 SVG 和 diagram manifest**
- **【待实现】组装后的 PPTX**
- 验证报告和分析 JSON
- 所有产物长期保存，不设置自动过期

## 4.3 本地运行目录负责什么

本地运行目录只作为：

- 接口上传文件的临时落盘位置
- `pptx_to_svg` 和 `svg_to_pptx` 的运行时工作目录
- 任务执行过程中的短期缓存

本地目录不是最终可信存储。

## 5. API Key 设计

## 5.1 调用方式

调用方请求服务时，需要传入自己的大模型 `api_key`。

建议接口层采用：

- 请求头：`X-LLM-API-Key`

不建议放在 URL 查询参数里。

## 5.2 数据库存储策略

关于 `api_key`，本轮直接采用最简单方案：

- 数据库中直接保存明文 `api_key`
- 不再保存 `api_key_hash`
- 不再保存 `api_key_ciphertext`
- 不再单独拆出用户主表
- 不再单独拆出 API Key 记录表

## 5.3 这样设计的影响

优点：

- 表结构更简单
- 联表更少
- 启动测试更快
- 按 `api_key` 查询任务更直接

代价：

- 明文密钥直接出现在数据库中
- 后续如果想升级到更严格的安全策略，需要再做一次迁移

因为你已经明确说现有数据表就是明文，所以本轮先按这个简单方案落地。

## 6. FTP 路径设计

虽然数据库里直接保存明文 `api_key`，但 FTP 目录**不建议**直接用原始 `api_key` 当目录名。

原因：

- 原始密钥可能包含不适合作为目录名的字符
- 直接把密钥暴露在文件路径中不利于后续管理

因此建议 FTP 路径只按模板和任务组织：

```text
/slides_gen_server/
├─ templates/{template_id}/
│  ├─ source/template.pptx
│  ├─ imported/svg/
│  ├─ imported/svg-flat/
│  └─ manifest/template_manifest.json
├─ generations/{generation_id}/                 # 【待实现】
│  ├─ request/request.json
│  ├─ input/requirement.md
│  └─ analysis/planning_manifest.json
└─ tasks/{task_id}/
   ├─ request/                                   # 旧模式兼容
   ├─ input/                                     # 旧模式兼容
   ├─ analysis/
   │  ├─ page_manifest.json                      # 【待实现】body
   │  └─ diagram_manifest.json                   # 【待实现】diagrams
   ├─ diagrams/{diagram_id}.svg                  # 【待实现】净化后单图
   ├─ svg_output/                                # 旧模式整页 SVG
   ├─ svg_final/                                 # 旧模式整页 SVG
   ├─ validation/
   └─ exports/
      ├─ body.pptx                               # 【待实现】
      ├─ composed.pptx                           # 【待实现】
      └─ generated.pptx                          # 旧模式
```

数据库里通过 `api_key` 字段表示调用方归属；FTP 路径里不再引入 `user_id`。

## 7. 任务控制与恢复设计

### 7.1 停止能力

当前旧接口保留 `stop_requested/stopping/stopped`。v4 新模式本期不新增或强化停止能力，避免扩大实施范围。

### 7.2 失败恢复是硬要求

允许恢复 `failed`，以及存在失败图形的 `completed_with_warnings` DiagramTask：

- BodyTask：只重做失败或缺失正文页；
- DiagramTask：只重做失败图形；
- ComposeTask：只重新执行本地组装；
- 已完成结果从 FTP 读取，不重复调用模型；
- 恢复完成后重新判断同一 generation 的自动组装依赖；
- 模板、planning manifest 或关键产物缺失时明确拒绝恢复。

### 7.3 状态枚举

执行任务状态：

- `pending/running/stopping/stopped/resuming/completed/completed_with_warnings/failed/cancelled`

Generation 聚合状态：

- `pending/running/completed/completed_with_warnings/failed`

聚合子状态还包括：

- `not_requested`：没有创建该类任务；
- `waiting`：ComposeTask 等待正文或图形前置条件。

完整状态语义以 [api_reference.md 第4.2节](api_reference.md#42-枚举值总表) 为准。

## 8. 接口补充设计

## 8.1 当前调用方任务列表

### `GET /api/v1/tasks`

作用：

- 查询当前 `api_key` 对应的任务列表
- 支持只返回任务 ID

建议参数：

- `only_ids`: bool，默认 `false`
- `status`: 可选，按状态过滤
- `page`: 可选
- `page_size`: 可选

当 `only_ids=true` 时，返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      "task_20260625_0001",
      "task_20260625_0002"
    ]
  }
}
```

## 8.2 停止任务接口

### `POST /api/v1/tasks/{task_id}/stop`

作用：

- 请求停止正在运行的任务

返回重点字段：

- `task_id`
- `status`
- `stop_requested`

## 8.3 恢复任务接口

### `POST /api/v1/tasks/{task_id}/resume`

作用：

- 恢复已停止或失败的任务

返回重点字段：

- `task_id`
- `status`
- `resume_count`

## 8.4 Generation 与图形接口【待实现】

- `POST /api/v1/generations`：创建输入并按 targets 创建子任务；
- `GET /api/v1/generations`：按当前 API Key 查询 Generation 列表；
- `GET /api/v1/generations/{generation_id}`：聚合查询；
- `POST /api/v1/generations/{generation_id}/tasks`：补触发 body/diagrams；
- `GET /api/v1/generations/{generation_id}/diagrams`：图形列表；
- `GET /api/v1/tasks/{task_id}/diagrams/{diagram_id}/preview`：直接 SVG 预览；
- `GET /api/v1/tasks/{task_id}/artifacts/{artifact_id}/download`：精确产物下载。

完整字段和样例见 [api_reference.md 第4节](api_reference.md#4-分离生成模式新增待实现)。

## 9. Pydantic Schema 设计约定

本项目后续 Schema 统一使用 `Pydantic`。

字段要求：

- 所有对外字段必须写 `description`
- 所有可选字段必须显式写 `default=None`
- `generation_id` 只表示输入聚合，`task_id` 只表示具体执行任务，两者不得混用

下面给出建议示例。

## 9.1 调用方识别 Schema

```python
from typing import Optional
from pydantic import BaseModel, Field


class ApiKeyIdentitySchema(BaseModel):
    api_key: str = Field(..., description="调用方传入的大模型 API Key，系统直接用它识别调用方")
    status: str = Field(..., description="当前调用方状态，例如 active 或 disabled")
    last_seen_at: Optional[str] = Field(default=None, description="最近一次使用该 API Key 的时间")
```

## 9.2 创建任务请求 Schema

```python
from typing import Optional
from pydantic import BaseModel, Field


class GenerationOptionsSchema(BaseModel):
    max_page_concurrency: Optional[int] = Field(default=None, description="单任务分页最大并发数")
    keep_artifacts: Optional[bool] = Field(default=None, description="是否保留中间产物到 FTP")
    output_filename: Optional[str] = Field(default=None, description="最终输出文件名建议")
    model: Optional[str] = Field(default=None, description="LLM 模型名称；为空时使用环境变量默认模型")
    enable_thinking: Optional[bool] = Field(default=False, description="是否启用模型思考模式")


class CreateGenerationTaskRequest(BaseModel):
    task_id: Optional[str] = Field(default=None, description="任务ID；为空时由服务端生成")
    requirement_text: str = Field(..., description="本次 PPT 生成需求全文")
    template_id: Optional[str] = Field(default=None, description="模板ID；为空时使用系统默认模板")
    options: Optional[GenerationOptionsSchema] = Field(default=None, description="任务执行参数")
```

## 9.3 任务响应 Schema

```python
from typing import Optional
from pydantic import BaseModel, Field


class GenerationTaskSummarySchema(BaseModel):
    task_id: str = Field(..., description="系统内部任务唯一ID")
    status: str = Field(..., description="任务状态")
    current_stage: str = Field(..., description="任务当前所处阶段")
    progress: float = Field(..., description="任务进度，范围 0 到 100")
    template_id: Optional[str] = Field(default=None, description="本次任务使用的模板ID")
    ftp_result_pptx_path: Optional[str] = Field(default=None, description="最终 PPTX 在 FTP 上的路径")
    error_message: Optional[str] = Field(default=None, description="任务失败时的错误信息")
```

## 9.4 分页状态 Schema

```python
from typing import Optional
from pydantic import BaseModel, Field


class GenerationTaskPageSchema(BaseModel):
    task_id: str = Field(..., description="所属任务ID")
    page_no: int = Field(..., description="页码，从 1 开始")
    page_name: Optional[str] = Field(default=None, description="页面名称")
    should_generate: Optional[bool] = Field(default=None, description="该页是否应保留到最终 PPT")
    skip_reason: Optional[str] = Field(default=None, description="页面被跳过时的原因")
    status: str = Field(..., description="分页执行状态")
    diagram_kind: Optional[str] = Field(default=None, description="图形类型，例如 architecture 或 sequence")
    ftp_generated_svg_path: Optional[str] = Field(default=None, description="原始生成 SVG 在 FTP 上的路径")
    ftp_final_svg_path: Optional[str] = Field(default=None, description="最终确认用于转 PPTX 的 SVG 在 FTP 上的路径")
    error_message: Optional[str] = Field(default=None, description="该页执行失败时的错误信息")
```

## 10. 数据库表设计

## 10.1 核心表清单

当前 DDL 包含以下 5 张表：

- `sg_template`
- `sg_generation_task`
- `sg_generation_task_page`
- `sg_generation_task_artifact`
- `sg_generation_task_event`

新模式增量迁移新增 2 张表：

- **`sg_generation_request`**：不可变输入与子任务聚合状态
- **`sg_generation_diagram`**：独立图形 metadata、状态和 FTP 路径

## 10.2 表职责说明

### `sg_template`

保存模板元数据及其 FTP 路径。

关键点：

- 使用 `api_key` 表示模板归属
- 内置模板允许 `api_key` 为空

### `sg_generation_task`

保存任务主记录。

关键点：

- 主键统一为 `task_id`
- 使用明文 `api_key` 表示任务归属
- 保存任务状态、阶段、进度、停止标记、恢复次数
- 保存最终 PPTX 的 FTP 路径

### `sg_generation_task_page`

保存分页生成状态。

关键点：

- 保存逐页 `should_generate`
- 保存逐页 `skip_reason`
- 保存逐页 SVG 产物路径
- 为任务恢复提供页级检查点

### `sg_generation_task_artifact`

保存所有产物文件的 FTP 路径清单。

适合记录：

- 请求快照
- 输入需求文件
- 分页分析结果
- 原始 SVG
- 最终 SVG
- 校验报告
- 最终 PPTX

### `sg_generation_task_event`

保存任务过程事件。

适合记录：

- 任务创建
- 状态变化
- 停止请求
- 恢复请求
- 导出成功
- 异常失败

### `sg_generation_request`【待实现】

保存 `generation_id`、完整 requirement_text、模板、auto_compose、三个 task ID、聚合状态和 planning manifest 路径。输入开始执行后冻结。

### `sg_generation_diagram`【待实现】

一行一个图形，保存所属 generation/task、章节标题、图形标题/类型、最终页码、证据摘录、校验状态、布局结果和 SVG FTP 路径。SVG-only 时最终页码为空。

## 11. SVG 落盘策略

- 旧模式：`svg_output` 和 `svg_final` 继续存 FTP；
- 新模式：模型原始 SVG 可作为内部诊断产物，安全净化并校验后的最终 SVG 必须存 FTP；
- 浏览器预览和用户下载均使用净化后的最终 SVG；
- 一图一个文件，并在 `sg_generation_diagram` 与 artifact 表分别记录业务 metadata 和通用文件 metadata；
- 失败恢复优先读取已完成 SVG，不重复调用模型；
- 本期所有 SVG 不设置自动过期。

## 12. 对实现阶段的直接约束

后续写代码时，请直接按以下原则实现：

- 服务启动时先连 MySQL
- 模板上传后先临时落本地，再上传 FTP；新模式不上传参考文档
- 新模式先写 `sg_generation_request`，再创建并提交子任务
- requirement_text 5万字告警、10万字拒绝，输入开始执行后冻结
- 每完成一页或一个图形，都更新对应检查点
- 每生成一个关键产物，都记录 `sg_generation_task_artifact`
- ComposeTask 只在同一 generation 的前置结果可用后创建
- 图形部分失败时保留成功产物并允许 `completed_with_warnings`
- 恢复优先读取数据库状态和 FTP 成功产物，只重做失败部分
- 所有查询按明文 `api_key` 校验归属
- 所有 FTP 产物长期保留，不做自动删除

## 13. 本文档对应的 DDL 文件

当前已实现建表脚本：

- `sql/mysql_init_v2.sql`

分离生成模式实现时：

- 新增独立增量迁移脚本，创建 `sg_generation_request`、`sg_generation_diagram` 并扩展现有表；
- 同步更新 `mysql_init_v2.sql` 供全新环境初始化；
- 迁移必须兼容历史任务，新增字段允许为空。
