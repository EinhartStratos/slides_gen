# MySQL 持久化、FTP 存储与任务控制补充设计

## 1. 文档目标

本文档是对以下两份设计文档的补充：

- `docs/prd_fastapi_svg_ppt_service.md`
- `docs/fastapi_service_architecture.md`

本补充文档专门回答并固化以下新增要求：

- 任务信息要存 MySQL，且要有清晰表结构
- 上传文件与生成结果要存 FTP，数据库记录路径
- 用户请求会传入大模型 `api_key`，系统要基于它识别用户并持久化
- 需要明确 SVG 是存 FTP 还是存数据库大字段
- 需要明确是否支持任务停止和恢复
- 需要给出 Pydantic Schema 设计示例，并给字段写清含义
- 需要提供可以直接导入本地测试库的 MySQL DDL

## 2. 最终设计结论

先直接给出本轮的核心结论：

- **任务主数据存 MySQL**
- **文件主数据存 FTP**
- **数据库只存元数据、状态、统计和 FTP 路径**
- **SVG 不存数据库大字段，统一存 FTP**
- **用户通过请求中的 `api_key` 识别**
- **数据库中至少保存 `api_key_hash`，如需恢复可额外保存加密密文**
- **首版必须支持任务停止**
- **首版建议支持受限恢复**
- **必须支持查询当前用户的全部任务 ID**

## 3. 为什么 SVG 不放数据库大字段

对于“生成过程中的 SVG 应该存 FTP，还是直接放在数据库大字段里”，本方案的建议非常明确：

- **不要把 SVG 放到数据库大字段里**
- **把 SVG 文件存到 FTP，数据库只记录路径和摘要**

原因如下：

- 单个任务可能有很多页，每页都可能有 `svg_output` 和 `svg_final`
- SVG 更适合文件级别的排查、下载、人工查看和二次处理
- 任务恢复时更适合直接复用 FTP 中的分页产物
- 大量大文本进入数据库会拖慢查询，也不利于索引和后续维护
- 后续如果需要把某些 SVG 单独下载给用户，FTP 方式天然更顺手

## 4. MySQL 与 FTP 的职责划分

## 4.1 MySQL 负责什么

MySQL 负责保存：

- 用户记录
- API Key 识别记录
- 模板记录
- 生成任务主记录
- 分页生成状态
- 任务事件日志
- 各类产物的 FTP 路径
- 停止 / 恢复相关状态

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

## 5. 用户识别与 API Key 设计

## 5.1 用户识别方式

调用方请求服务时，需要传入自己的大模型 `api_key`。

建议接口层采用：

- 请求头：`X-LLM-API-Key`

不建议放在 URL 查询参数里。

## 5.2 数据库存储策略

关于 `api_key`，建议这样存：

- `api_key_hash`：必须存，用于用户识别和去重
- `api_key_masked`：建议存，用于页面展示和排查
- `api_key_ciphertext`：可选存，用于支持任务恢复时继续调用原始模型

不建议：

- 明文长期存储原始 `api_key`

## 5.3 为什么还要保存加密密文

如果只保存哈希值，那么：

- 可以识别用户
- 但不能在任务恢复时继续使用原始密钥去调用大模型

因此如果你希望：

- 任务停止后恢复
- 任务失败后继续执行未完成页

那么系统需要有能力取回原始密钥。

所以推荐方案是：

- 识别用户靠 `api_key_hash`
- 恢复任务靠 `api_key_ciphertext`

## 5.4 用户与任务关系

每个任务必须绑定：

- `owner_user_id`
- `user_api_key_id`

这样后续就能支持：

- 查询当前用户全部任务
- 查询当前用户全部任务 ID
- 按用户隔离任务与文件目录

## 6. FTP 路径设计

建议统一使用如下目录规则：

```text
/slides_gen_server/
├─ users/
│  └─ {user_id}/
│     ├─ templates/
│     │  └─ {template_id}/
│     │     ├─ source/template.pptx
│     │     ├─ imported/svg/
│     │     ├─ imported/svg-flat/
│     │     └─ manifest/template_manifest.json
│     └─ jobs/
│        └─ {job_id}/
│           ├─ request/request.json
│           ├─ input/requirement.md
│           ├─ analysis/
│           ├─ svg_output/
│           ├─ svg_final/
│           ├─ validation/
│           └─ exports/generated.pptx
```

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
- 如果密钥不可用、模板缺失或关键产物缺失，则拒绝恢复

## 7.3 停止机制

设计方式：

- 在任务表中维护 `stop_requested`
- 任务状态支持 `stopping`
- 编排器在阶段边界和分页边界检查停止标记
- 一旦命中安全边界，就把任务状态改为 `stopped`

## 7.4 恢复机制

恢复时执行：

- 读取任务主表状态
- 校验模板与用户密钥仍可用
- 读取分页表状态
- 跳过 `completed` 页面
- 重新执行 `pending`、`running`、`failed` 页面
- 汇总已有 `svg_final` 和新产出页面后再导出 PPTX

## 7.5 推荐任务状态

建议任务状态扩展为：

- `pending`
- `running`
- `stopping`
- `stopped`
- `resuming`
- `completed`
- `failed`
- `cancelled`

## 8. 接口补充设计

## 8.1 当前用户任务列表

### `GET /api/v1/users/me/jobs`

作用：

- 查询当前用户的任务列表
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
      "job_20260625_0001",
      "job_20260625_0002"
    ]
  }
}
```

## 8.2 停止任务接口

### `POST /api/v1/generation-jobs/{job_id}/stop`

作用：

- 请求停止正在运行的任务

返回重点字段：

- `job_id`
- `status`
- `stop_requested`

## 8.3 恢复任务接口

### `POST /api/v1/generation-jobs/{job_id}/resume`

作用：

- 恢复已停止或失败的任务

返回重点字段：

- `job_id`
- `status`
- `resume_count`

## 9. Pydantic Schema 设计约定

本项目后续 Schema 统一使用 `Pydantic`。

字段要求：

- 所有对外字段必须写 `description`
- 所有可选字段必须显式写 `default=None`
- 兼容字段必须明确写清与主字段的映射关系

下面给出建议示例。

## 9.1 用户识别 Schema

```python
from typing import Optional
from pydantic import BaseModel, Field


class UserIdentitySchema(BaseModel):
    user_id: str = Field(..., description="系统内部用户唯一ID")
    api_key_hash: str = Field(..., description="大模型 API Key 的哈希值，用于识别用户")
    api_key_masked: str = Field(..., description="脱敏后的 API Key，仅用于展示和排查")
    status: str = Field(..., description="用户状态，例如 active 或 disabled")
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


class CreateGenerationJobRequest(BaseModel):
    requirement_text: str = Field(..., description="本次 PPT 生成需求全文")
    template_id: Optional[str] = Field(default=None, description="模板ID；为空时使用系统默认模板")
    conversation_id: Optional[str] = Field(default=None, description="兼容字段：会话ID，默认等同 job_id")
    task_id: Optional[str] = Field(default=None, description="兼容字段：等同conversation_id")
    options: Optional[GenerationOptionsSchema] = Field(default=None, description="任务执行参数")
```

## 9.3 任务响应 Schema

```python
from typing import Optional
from pydantic import BaseModel, Field


class GenerationJobSummarySchema(BaseModel):
    job_id: str = Field(..., description="系统内部任务唯一ID")
    conversation_id: Optional[str] = Field(default=None, description="兼容字段：默认等同 job_id")
    task_id: Optional[str] = Field(default=None, description="兼容字段：等同conversation_id")
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


class GenerationJobPageSchema(BaseModel):
    job_id: str = Field(..., description="所属任务ID")
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

本次 DDL 建议包含以下 7 张核心表：

- `sg_user`
- `sg_user_api_key`
- `sg_template`
- `sg_generation_job`
- `sg_generation_job_page`
- `sg_generation_job_artifact`
- `sg_generation_job_event`

## 10.2 表职责说明

### `sg_user`

保存用户主记录。

### `sg_user_api_key`

保存用户 API Key 识别记录。

说明：

- 一个用户可以有多个密钥记录
- 系统通过 `api_key_hash` 识别用户
- 如需任务恢复，可使用 `api_key_ciphertext`

### `sg_template`

保存模板元数据及其 FTP 路径。

### `sg_generation_job`

保存任务主记录。

关键点：

- 保存任务状态、阶段、进度、停止标记、恢复次数
- 保存与模板、用户、密钥的关联
- 保存最终 PPTX 的 FTP 路径

### `sg_generation_job_page`

保存分页生成状态。

关键点：

- 保存逐页 `should_generate`
- 保存逐页 `skip_reason`
- 保存逐页 SVG 产物路径
- 为任务恢复提供页级检查点

### `sg_generation_job_artifact`

保存所有产物文件的 FTP 路径清单。

适合记录：

- 请求快照
- 输入需求文件
- 分页分析结果
- 原始 SVG
- 最终 SVG
- 校验报告
- 最终 PPTX

### `sg_generation_job_event`

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
- 每生成一个关键产物，都要记录 `sg_generation_job_artifact`
- 停止请求只改数据库标记，不强杀线程
- 恢复任务时，优先读取数据库分页状态和 FTP 中的已完成产物

## 13. 本文档对应的 DDL 文件

本补充设计对应的建表脚本文件为：

- `sql/mysql_init.sql`

该脚本目标：

- 你可以直接导入本地测试库
- 后续 FastAPI 服务启动时可以直接连库联调
