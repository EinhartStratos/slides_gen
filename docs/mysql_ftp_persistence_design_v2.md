# MySQL 持久化、FTP 存储与任务控制补充设计 V2

## 1. 文档目标

本文档是对现有设计的收敛版补充，按最新确认要求重新统一以下规则：

- 不再引入 `user_id`
- 不再对 `api_key` 做哈希存储或加密存储
- 所有业务表直接使用明文 `api_key`
- 不再并存 `job_id`、`conversation_id`、`task_id`
- 任务主键统一只保留 `task_id`

这份文档优先于旧版补充设计文档，用于指导下一步代码实现。

## 2. 最终设计结论

本轮最新口径如下：

- **任务主数据存 MySQL**
- **文件主数据存 FTP**
- **数据库只存元数据、状态、统计和 FTP 路径**
- **SVG 不存数据库大字段，统一存 FTP**
- **系统通过请求中的明文 `api_key` 识别调用方**
- **各业务表直接保存明文 `api_key`**
- **不再单独设计用户表和 API Key 表**
- **任务主键统一使用 `task_id`**
- **首版必须支持任务停止**
- **首版建议支持受限恢复**
- **必须支持按当前 `api_key` 查询全部任务 ID**

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
- 生成任务主记录
- 分页生成状态
- 任务事件日志
- 各类产物的 FTP 路径
- 停止 / 恢复相关状态
- 调用方对应的明文 `api_key`

## 4.2 FTP 负责什么

FTP 负责保存：

- 用户上传的模板 PPTX
- 模板导入后的 SVG 工作区
- 任务运行中产生的 `svg_output/`
- 任务最终确认可转 PPTX 的 `svg_final/`
- 验证报告、请求快照、分页分析 JSON
- 最终导出的 PPTX

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
├─ templates/
│  └─ {template_id}/
│     ├─ source/template.pptx
│     ├─ imported/svg/
│     ├─ imported/svg-flat/
│     └─ manifest/template_manifest.json
└─ tasks/
   └─ {task_id}/
      ├─ request/request.json
      ├─ input/requirement.md
      ├─ analysis/
      ├─ svg_output/
      ├─ svg_final/
      ├─ validation/
      └─ exports/generated.pptx
```

数据库里通过 `api_key` 字段表示调用方归属；FTP 路径里不再引入 `user_id`。

## 7. 任务停止与恢复设计

## 7.1 是否需要支持停止

建议：**必须支持**。

原因：

- 任务执行时间长
- 中途有多次 LLM 调用
- 成本高
- 用户可能临时取消需求或发现输入有问题

## 7.2 是否需要支持恢复

建议：**支持，但做受限恢复**。

这里的“受限恢复”是指：

- 只允许恢复 `stopped` 或 `failed` 的任务
- 只恢复未完成页和失败页
- 已完成页直接复用已落 FTP 的产物
- 如果模板缺失或关键产物缺失，则拒绝恢复

## 7.3 停止机制

设计方式：

- 在任务表中维护 `stop_requested`
- 任务状态支持 `stopping`
- 编排器在阶段边界和分页边界检查停止标记
- 一旦命中安全边界，就把任务状态改为 `stopped`

## 7.4 恢复机制

恢复时执行：

- 读取任务主表状态
- 校验模板仍可用
- 读取分页表状态
- 跳过 `completed` 页面
- 重新执行 `pending`、`running`、`failed` 页面
- 汇总已有 `svg_final` 和新产出页面后再导出 PPTX

## 7.5 推荐任务状态

建议任务状态为：

- `pending`
- `running`
- `stopping`
- `stopped`
- `resuming`
- `completed`
- `failed`
- `cancelled`

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

## 9. Pydantic Schema 设计约定

本项目后续 Schema 统一使用 `Pydantic`。

字段要求：

- 所有对外字段必须写 `description`
- 所有可选字段必须显式写 `default=None`
- 任务标识统一只保留 `task_id`

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

本次 DDL 建议包含以下 5 张核心表：

- `sg_template`
- `sg_generation_task`
- `sg_generation_task_page`
- `sg_generation_task_artifact`
- `sg_generation_task_event`

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

## 11. SVG 落盘策略

建议如下：

- `svg_final`：建议始终存 FTP
- `svg_output`：建议在 `keep_artifacts=true` 时存 FTP
- 如果开启任务恢复，建议 `svg_output` 也保留

更保守的首版策略是：

- 只要任务不是临时试跑，就把 `svg_output` 和 `svg_final` 都存 FTP

这样后续定位问题更方便。

## 12. 对实现阶段的直接约束

后续写代码时，请直接按以下原则实现：

- 服务启动时先连 MySQL
- 文件上传后先临时落本地，再上传 FTP
- 任务创建成功后必须先写 MySQL 主记录，再进入后台编排
- 每完成一页，都要更新分页表
- 每生成一个关键产物，都要记录 `sg_generation_task_artifact`
- 停止请求只改数据库标记，不强杀线程
- 恢复任务时，优先读取数据库分页状态和 FTP 中的已完成产物
- 所有按用户维度的查询，统一改为按 `api_key` 过滤

## 13. 本文档对应的 DDL 文件

本补充设计对应的建表脚本文件为：

- `sql/mysql_init_v2.sql`

该脚本目标：

- 你可以直接导入本地测试库
- 后续 FastAPI 服务启动时可以直接连库联调
