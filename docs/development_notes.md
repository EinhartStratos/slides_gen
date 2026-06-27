# slides_gen_server 开发说明

## 1. 当前实现结构

项目当前采用标准 FastAPI 分层结构，核心目录如下：

```text
app/
├─ api/                    接口层
├─ core/                   配置、常量、异常
├─ schemas/                Pydantic 数据模型
├─ services/               业务编排与应用服务
├─ infrastructure/         数据库、存储、LLM、PPT 适配器
│  ├─ db/
│  ├─ storage/
│  ├─ llm/
│  └─ ppt_master/
├─ vendor/                 项目内置的第三方运行时代码
│  └─ ppt_master/
└─ main.py
```

## 2. 运行时依赖调整

为避免后续删除参考目录后影响运行，PPT 转换相关运行时代码已迁入：

- `app/vendor/ppt_master/scripts/pptx_to_svg`
- `app/vendor/ppt_master/scripts/svg_to_pptx`
- `app/vendor/ppt_master/scripts/svg_finalize`
- `app/vendor/ppt_master/templates/icons`

当前服务运行时不再依赖项目外部参考目录。

## 3. 存储策略

当前存储层采用“本地 mock FTP + 可选远程 FTP”的方式：

- 未配置 `FTP_HOST` 时：只使用本地 `mock_ftp/`
- 配置了远程 FTP 时：远程 FTP 与本地 `mock_ftp/` 同步保留

这样做的目的：

- 本地调试时不用依赖真实 FTP
- 所有上传产物都能直接在仓库根目录查看
- 即使远程 FTP 临时异常，也更容易回退排查

## 4. 模板策略

当前模板分为两类：

- 公共基础模板：`is_builtin=1`，所有调用方都可使用
- 私有模板：带 `api_key` 归属，只允许所属调用方使用

当前约定：

- `POST /api/v1/templates/import` 导入私有模板，需要 `X-LLM-API-Key`
- `POST /api/v1/templates/import-builtin` 导入公共基础模板，不需要 `X-LLM-API-Key`
- 当创建任务不传 `template_id` 时，会优先使用默认基础模板
- 默认基础模板来源为项目根目录的 `templete.pptx`

## 5. 当前生成链路

当前任务主链路如下：

1. 创建任务并持久化到 MySQL
2. 将请求和需求文件写入任务工作区
3. 从模板工作区复制模板平铺 SVG 与资源
4. 对每页进行分析
5. 基于分析结果在模板 SVG 上追加受控文本内容
6. 校验最终 SVG
7. 导出最终 PPTX
8. 将产物写入 `mock_ftp/` 与可选远程 FTP

## 6. 已补齐的缺失模块

本轮已补充：

- LLM 分页分析基础模块
- Prompt 构建器
- OpenAI 风格接口适配器
- 无模型配置时的本地启发式回退逻辑
- 基于分析结果的受控 SVG 内容叠加
- 任务事件查询接口

## 7. 当前仍待继续完善的点

当前仍建议继续完善以下内容：

- 更精细的模板页结构识别，而不只是基于整页 SVG 片段做分析
- 更稳定的可编辑 SVG 布局生成器
- 图形页的结构化中间结果渲染器
- 更严格的 SVG 白名单校验
- 自动化测试

## 8. 相关设计文档

可继续参考以下文档：

- `docs/fastapi_service_architecture.md`
- `docs/mysql_ftp_persistence_design_v2.md`
- `sql/mysql_init_v2.sql`
