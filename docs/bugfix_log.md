# 问题修复记录

> 本文只记录已经完成的历史修复，不描述待实现功能。分离生成模式的最终方案见 [ppt_body_diagram_separated_generation_plan.md](ppt_body_diagram_separated_generation_plan.md)，新增 API 契约见 [api_reference.md 第4节](api_reference.md#4-分离生成模式新增待实现)。

## 1. LLM API 返回 HTTP 400（DeepSeek）

- **原因**：DeepSeek API 不支持 `enable_thinking` 参数，但请求 payload 中始终包含该字段
- **修复**：仅在 `enable_thinking=True` 时才将该参数加入 payload

## 2. 流式响应错误体无法读取（ResponseNotRead）

- **原因**：流式 HTTP 请求返回 400 时，直接访问 `response.text` 会失败，因为响应体尚未被 `read()`
- **修复**：在 `_call_stream` 中先调用 `response.read()` 读取并记录错误体，再 `raise_for_status()`

## 3. 数据库 progress 字段溢出

- **原因**：`_process_structured_page` 中 `_update_progress` 传入 `total_pages=1`（硬编码），但 `counters["processed"]` 是全局计数器，导致 `progress = 10 + (processed / 1) * 80` 超过 100
- **修复**：传入实际 `total_pages`，并在 `_update_progress` 中加 `min(..., 90)` 安全上限

## 4. skipped_pages 变量类型覆盖

- **原因**：`skipped_pages` 原为 `set[int]`（用于混合导出），但在计数器汇总时被 `counters["skipped"]`（`int`）覆盖，导致 `len(skipped_pages)` 报错
- **修复**：计数器值改用 `skipped_count` 变量名，保持 `skipped_pages` 类型不变

## 5. SVG 注入失败（spTree 未找到）

- **原因**：`_inject_svg_slide` 中用 `find("p:spTree")` 搜索 `p:sld` 的直接子元素，但 `spTree` 嵌套在 `p:cSld` 下
- **修复**：先查找 `p:cSld`，再从中查找 `p:spTree`

## 6. 导出异常被静默吞掉

- **原因**：`run_task` 的 `except` 块中没有 `logger.error`，导出失败时看不到任何错误信息
- **修复**：添加 `logger.error("任务执行失败: %s", exc, exc_info=True)` 和导出阶段关键节点日志
