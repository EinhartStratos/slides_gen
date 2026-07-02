# LLM 请求并发设计文档（已实现）

## 1. 背景

### 1.1 串行实现（改造前）

> **状态：已改造为并发模式，见下文。**

改造前 `orchestration_service.run_task` 中的处理流程是**纯串行**的：

```
阶段1：plan_pages() → 逐页串行调用 LLM 规划（全部完成后才进入阶段2）
阶段2：for 循环逐页 → 串行调用 LLM 生成 SVG → 校验 → 上传 FTP
```

- `plan_pages` 内部 `for` 循环逐页调用 `plan_single_page`，每页等待 LLM 返回后才处理下一页
- 生成阶段同样在 `for` 循环中逐页调用 `generate_page_svg`，每页等待完成后才处理下一页
- 两个阶段**严格分离**：必须所有页面规划完毕后，才开始生成

### 1.2 问题

假设模板有 15 页，每页 LLM 请求耗时 8 秒：
- 规划阶段：15 × 8s = 120s
- 生成阶段：15 × 8s = 120s
- 总计：240s（约 4 分钟）

如果并发 4 个请求：理论上可缩短到约 60s，节省 75% 时间。

---

## 2. 设计方案：全局并发 + 统一队列

### 2.1 核心思路

- **一个全局信号量**控制所有 LLM 请求的并发上限，不区分单任务
- **不区分规划池和生成池**，所有 LLM 请求（规划 + 生成）统一排队
- 每页作为一个独立任务提交：先规划，规划完直接生成，无需等全部规划完
- 多用户同时使用时，所有任务的 LLM 请求共享同一个全局并发额度

### 2.2 架构图

```text
┌───────────────────────────────────────────────────────────────┐
│                        全局层                                   │
│                                                                │
│   GLOBAL_LLM_SEMAPHORE (MAX_LLM_CONCURRENCY)                   │
│   ┌─────────────────────────────────────────────────┐          │
│   │  所有任务的 LLM 请求（规划+生成）都经过此信号量    │          │
│   └─────────────────────────────────────────────────┘          │
│                            │                                    │
├────────────────────────────┼────────────────────────────────────┤
│                        任务层                                    │
│                            │                                    │
│   ┌────────────────────────▼──────────────────────────┐        │
│   │              Task A (run_task)                      │        │
│   │                                                    │        │
│   │   ThreadPoolExecutor(max_workers=total_pages)      │        │
│   │                                                    │        │
│   │   page 1 ──→ plan ──→ generate ──→ render+upload   │        │
│   │   page 2 ──→ plan ──→ generate ──→ render+upload   │        │
│   │   page 3 ──→ plan ──→ (skip, 不生成)               │        │
│   │   ...                                              │        │
│   │   page N ──→ plan ──→ generate ──→ render+upload   │        │
│   │                                                    │        │
│   │   每页独立处理，规划完直接生成，不等其他页            │        │
│   │   LLM 调用前 acquire 信号量，调用完 release         │        │
│   └────────────────────────────────────────────────────┘        │
│                                                                │
│   ┌────────────────────────────────────────────────────┐        │
│   │              Task B (run_task)                      │        │
│   │   同样结构，共享同一个全局信号量                      │        │
│   └────────────────────────────────────────────────────┘        │
│                                                                │
│   全部页面完成 → 按页码排序 SVG → 导出 PPTX                      │
└───────────────────────────────────────────────────────────────┘
```

### 2.3 为什么不区分规划和生成池

| 考量 | 说明 |
|------|------|
| **页面间无依赖** | 第 N 页的规划不依赖其他页的规划结果，第 N 页的生成只依赖自己的规划结果 |
| **最大化吞吐** | 统一排队意味着只要全局有额度，任何 LLM 请求都能立即发出，不会出现"规划池空了但生成池排队"的浪费 |
| **实现最简** | 一个信号量 + 每页一个 Future，不需要中间队列、不需要两个线程池协调 |
| **全局公平** | 多用户时，所有请求公平竞争全局额度，不会因为某用户的规划阶段占满独立池而阻塞其他用户 |

### 2.4 与分池方案的对比

| 维度 | 统一队列（本方案） | 分规划/生成池 |
|------|-------------------|--------------|
| 性能 | 最优：无等待空窗 | 中：规划全部完成后才开始生成 |
| 复杂度 | 最低：一个信号量 | 中：两个池 + 中间队列 |
| 多用户公平 | 好：全局统一排队 | 中：各池独立可能分配不均 |
| 灵活性 | 中：无法单独控制规划/生成并发 | 高：可分别设并发数 |
| 页面顺序 | 完成顺序不固定，需排序 | 同样不固定 |

---

## 3. 详细设计

### 3.1 环境变量

```env
# LLM 全局并发控制
MAX_LLM_CONCURRENCY=8       # 全局 LLM 请求最大并发数（所有任务共享）
LLM_RATE_LIMIT_MAX_RETRIES=5  # 429 限流时最大重试次数
LLM_RATE_LIMIT_BASE_DELAY=1.0  # 限流退避基础延迟（秒）
LLM_RATE_LIMIT_MAX_DELAY=60.0  # 限流退避最大延迟（秒）
```

- `MAX_LLM_CONCURRENCY`：全局唯一并发控制。不管多少用户、多少任务同时运行，正在执行的 LLM 请求不超过此值
- 不需要单任务并发配置：每个任务内部所有页面同时提交到线程池，由全局信号量控制实际并发

### 3.2 全局信号量

在应用启动时创建一次，所有任务共享：

```python
# app/infrastructure/llm/concurrency.py
import threading

_global_semaphore: threading.Semaphore | None = None
_lock = threading.Lock()

def init_global_semaphore(max_concurrency: int) -> None:
    """在应用启动时调用（bootstrap.build_services 中）"""
    global _global_semaphore
    with _lock:
        if _global_semaphore is None:
            _global_semaphore = threading.Semaphore(max_concurrency)

def get_global_semaphore() -> threading.Semaphore:
    if _global_semaphore is None:
        raise RuntimeError("全局信号量未初始化，请先调用 init_global_semaphore()")
    return _global_semaphore
```

### 3.3 LLM 客户端改造

在 `_call_llm` 中加入信号量获取和 429 限流退避：

```python
# app/infrastructure/llm/openai_like_client.py

import random
import time as time_module
import httpx2

from app.infrastructure.llm.concurrency import get_global_semaphore

class OpenAILikePageGenerationClient(BasePageGenerationClient):

    def _call_llm_with_limit(
        self,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        use_json: bool = False,
        stream: bool = True,
        model: str | None = None,
        enable_thinking: bool = False,
    ) -> str:
        """
        带全局并发控制和限流退避的 LLM 调用。
        信号量在 LLM 请求期间持有，请求完成（含重试）后释放。
        """
        semaphore = get_global_semaphore()
        max_retries = self.settings.llm_rate_limit_max_retries
        base_delay = self.settings.llm_rate_limit_base_delay
        max_delay = self.settings.llm_rate_limit_max_delay

        payload = self._build_payload(system_prompt, user_prompt, use_json, stream, model, enable_thinking)
        headers = self._build_headers(api_key)
        timeout = httpx2.Timeout(self.settings.llm_timeout_seconds, connect=30.0)

        semaphore.acquire()
        try:
            for attempt in range(1, max_retries + 1):
                try:
                    if stream:
                        return self._call_stream(payload, headers, timeout)
                    return self._call_non_stream(payload, headers, timeout)
                except httpx2.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    if status_code == 429:
                        # 限流退避
                        delay = self._calculate_backoff(
                            exc.response, attempt, base_delay, max_delay
                        )
                        logger.warning(
                            "LLM 请求被限流 (429, attempt=%s/%s)，等待 %.1fs 后重试",
                            attempt, max_retries, delay,
                        )
                        time_module.sleep(delay)
                        continue
                    # 其他 HTTP 错误直接抛出
                    raise
                except (httpx2.ConnectError, httpx2.ReadTimeout, httpx2.WriteTimeout) as exc:
                    # 网络错误也做退避重试
                    delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1), max_delay)
                    logger.warning(
                        "LLM 请求网络错误 (attempt=%s/%s): %s，等待 %.1fs 后重试",
                        attempt, max_retries, exc, delay,
                    )
                    if attempt < max_retries:
                        time_module.sleep(delay)
                        continue
                    raise
            # 重试次数用尽
            raise RuntimeError(f"LLM 请求在 {max_retries} 次重试后仍被限流")
        finally:
            semaphore.release()

    @staticmethod
    def _calculate_backoff(
        response: httpx2.Response,
        attempt: int,
        base_delay: float,
        max_delay: float,
    ) -> float:
        """
        计算退避时间：
        1. 优先读取 Retry-After 响应头（秒）
        2. 没有 Retry-After 时，使用指数退避 + 随机抖动
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                # Retry-After 可能是 HTTP-date 格式，尝试解析
                delay = base_delay * (2 ** (attempt - 1))
        else:
            # 指数退避: base * 2^(attempt-1) + 随机抖动
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
        return min(delay, max_delay)
```

### 3.4 编排服务改造

`orchestration_service.run_task` 中，将串行 for 循环改为并发提交：

```python
# app/services/orchestration_service.py

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

async def run_task(self, api_key: str, task_id: str) -> None:
    # ... 前置准备（模板加载、目录创建等）不变 ...

    # 解析参数
    llm_model = options.get("model")
    llm_enable_thinking = options.get("enable_thinking", False)

    total_pages = len(source_svgs)

    # 线程安全计数器
    lock = threading.Lock()
    counters = {
        "processed": 0,
        "completed": 0,
        "skipped": 0,
        "failed": 0,
    }

    def update_counters(field: str, delta: int = 1):
        with lock:
            counters[field] += delta
            processed = counters["processed"]
            progress = 10 + (processed / max(total_pages, 1)) * 80
            self.task_service.repository.update_task(task_id, {
                "processed_pages": counters["processed"],
                "completed_pages": counters["completed"],
                "skipped_pages": counters["skipped"],
                "failed_pages": counters["failed"],
                "progress": round(progress, 2),
                "last_heartbeat_at": datetime.now(),
            })

    # 每页一个任务，全部提交到线程池
    # 线程池大小 = total_pages（实际并发由全局信号量控制）
    with ThreadPoolExecutor(max_workers=total_pages, thread_name_prefix=f"task-{task_id}") as executor:
        futures = {}
        for index, source_svg in enumerate(source_svgs, start=1):
            future = executor.submit(
                self._process_one_page,
                api_key=api_key,
                task_id=task_id,
                requirement_text=str(task["requirement_text"]),
                page_no=index,
                source_svg=source_svg,
                page_plan=plan_map.get(index, {}),  # 如果仍需要预规划
                llm_model=llm_model,
                llm_enable_thinking=llm_enable_thinking,
                task_workspace=task_workspace,
                task=task,
                counters=counters,
                lock=lock,
            )
            futures[index] = future

        # 等待全部完成
        for future in as_completed(futures.values()):
            future.result()  # 异常会在此抛出

    # 全部页面完成，导出 PPTX
    # ... 后续逻辑不变 ...
```

### 3.5 单页处理方法

```python
def _process_one_page(
    self,
    api_key: str,
    task_id: str,
    requirement_text: str,
    page_no: int,
    source_svg: Path,
    llm_model: str | None,
    llm_enable_thinking: bool,
    task_workspace,
    task: dict,
    counters: dict,
    lock: threading.Lock,
) -> None:
    """单页完整处理：规划 → 生成 → 渲染 → 校验 → 上传"""

    # 1. 检查停止标志
    latest_task = self.task_service.get_task(api_key, task_id)
    if latest_task["stop_requested"]:
        return

    # 2. 检查是否已完成（断点续做）
    page_row = existing_pages.get(page_no)
    if page_row and page_row["status"] == PAGE_STATUS_COMPLETED:
        # 已完成，跳过
        with lock:
            counters["processed"] += 1
            counters["completed"] += 1
        return

    # 3. 规划
    plan = self.slide_service.plan_single_page(
        api_key=api_key,
        requirement_text=requirement_text,
        page_no=page_no,
        page_name=source_svg.stem,
        svg_content=source_svg.read_text(encoding="utf-8", errors="ignore"),
        total_pages=total_pages,
        model=llm_model,
        enable_thinking=llm_enable_thinking,
    )

    if not plan.should_generate:
        # 跳过
        self._handle_skipped_page(...)
        with lock:
            counters["processed"] += 1
            counters["skipped"] += 1
        return

    # 4. 生成
    result = self.slide_service.generate_page_svg(
        api_key=api_key,
        requirement_text=requirement_text,
        page_no=page_no,
        source_svg_path=source_svg,
        page_plan=plan.model_dump(mode="json"),
        model=llm_model,
        enable_thinking=llm_enable_thinking,
    )

    if result.decision_source == "failed":
        self._handle_failed_page(...)
        with lock:
            counters["processed"] += 1
            counters["failed"] += 1
        return

    # 5. 渲染 + 校验 + 上传
    self._render_and_upload_page(...)
    with lock:
        counters["processed"] += 1
        counters["completed"] += 1
```

### 3.6 信号量初始化

在 `app/services/bootstrap.py` 的 `build_services` 中初始化：

```python
from app.infrastructure.llm.concurrency import init_global_semaphore

def build_services(settings: Settings) -> ServiceContainer:
    # 初始化全局 LLM 并发信号量
    init_global_semaphore(settings.max_llm_concurrency)
    # ... 其余初始化 ...
```

### 3.7 文件改动清单（已实现）

| 文件 | 改动内容 | 状态 |
|------|----------|------|
| `app/core/config.py` | 新增 `max_llm_concurrency`、`llm_rate_limit_max_retries`、`llm_rate_limit_base_delay`、`llm_rate_limit_max_delay` 字段 | ✅ |
| `.env` | 新增 `MAX_LLM_CONCURRENCY=8`、`LLM_RATE_LIMIT_MAX_RETRIES=5`、`LLM_RATE_LIMIT_BASE_DELAY=1.0`、`LLM_RATE_LIMIT_MAX_DELAY=60.0` | ✅ |
| `app/infrastructure/llm/concurrency.py` | **新建**：全局信号量管理（`init_global_semaphore` / `get_global_semaphore` / `reset_global_semaphore`） | ✅ |
| `app/infrastructure/llm/openai_like_client.py` | `_call_llm` 加入信号量 + 429 退避 + 网络错误退避；新增 `_calculate_backoff` 静态方法 | ✅ |
| `app/services/bootstrap.py` | `build_services` 中调用 `init_global_semaphore` | ✅ |
| `app/services/orchestration_service.py` | `run_task` 改为 `ThreadPoolExecutor` 并发提交，提取 `_process_one_page` 和 `_update_progress` 方法 | ✅ |
| `app/services/slide_generation_service.py` | 重构 `plan_pages` 为调用 `plan_single_page`，供并发编排使用 | ✅ |
| `tests/test_concurrency.py` | **新建**：16 个测试覆盖信号量、429 退避、网络错误退避、退避计算 | ✅ |
| `tests/conftest.py` | `test_settings` 新增 4 个并发配置字段 | ✅ |
| `tests/test_llm_client.py` | `make_settings` 新增 4 个并发配置字段；`make_client` 初始化信号量 | ✅ |
| `tests/test_ftp_storage.py` | 两处 `Settings` 构造新增 4 个并发配置字段 | ✅ |
| `tests/test_slide_generation_service.py` | `Settings` 构造新增 4 个并发配置字段 | ✅ |

---

## 4. 限流退避详细设计

### 4.1 退避策略

```text
收到 429 响应
  │
  ├─ 有 Retry-After 头？
  │    ├─ 是 → 等待 Retry-After 秒数
  │    └─ 否 → 指数退避: base_delay × 2^(attempt-1) + random(0,1)
  │
  ├─ 计算出的延迟 > max_delay？
  │    └─ 是 → 截断为 max_delay
  │
  └─ sleep(delay) → 重试
```

### 4.2 退避时间示例

假设 `base_delay=1.0`，`max_delay=60.0`：

| 重试次数 | 无 Retry-After | 有 Retry-After=5 | 有 Retry-After=120 |
|----------|---------------|-----------------|-------------------|
| 1 | 1.0 + jitter ≈ 1.5s | 5s | 60s（截断） |
| 2 | 2.0 + jitter ≈ 2.5s | 5s | 60s（截断） |
| 3 | 4.0 + jitter ≈ 4.5s | 5s | 60s（截断） |
| 4 | 8.0 + jitter ≈ 8.5s | 5s | 60s（截断） |
| 5 | 16.0 + jitter ≈ 16.5s | 5s | 60s（截断） |

### 4.3 与现有重试逻辑的关系

当前 `plan_single_page` 和 `generate_page_svg` 各有 3 次重试逻辑（固定 2s、4s 间隔）。改造后：

- **内层重试（新增）**：在 `_call_llm_with_limit` 中处理 429 和网络错误，最多 `LLM_RATE_LIMIT_MAX_RETRIES` 次
- **外层重试（保留）**：`plan_single_page` / `generate_page_svg` 的 3 次重试仍然保留，处理内层重试耗尽后的兜底
- 外层重试的固定间隔也改为指数退避

```text
外层重试（plan_single_page / generate_page_svg）
  └─ 内层重试（_call_llm_with_limit）
       └─ 429 → 退避 → 重试
       └─ 网络错误 → 退避 → 重试
       └─ 内层重试耗尽 → 抛出异常 → 外层捕获 → 外层退避 → 再次内层重试
```

### 4.4 网络错误退避

除 429 外，以下错误也做退避重试：
- `httpx2.ConnectError`：连接失败
- `httpx2.ReadTimeout`：读取超时
- `httpx2.WriteTimeout`：写入超时

退避策略与 429 相同（指数退避 + 抖动），但无 Retry-After 可读。

---

## 5. 多用户并发问题与解决方案

### 5.1 无问题项

- **LLM 客户端**：`OpenAILikePageGenerationClient` 无实例状态，每次调用创建独立 `httpx2.Client`，线程安全
- **FTP 存储**：每个任务有独立 FTP 路径（`/tasks/{task_id}/`），不会冲突
- **Runtime 目录**：每个任务有独立 `runtime/tasks/{task_id}/` 目录，不会冲突

### 5.2 潜在问题与解决方案

#### 5.2.1 LLM API 限流

**问题**：多用户并发时，总 LLM 请求数可能超过 API 限制。

**解决方案**：
1. **全局信号量**：`MAX_LLM_CONCURRENCY` 限制全局并发，所有任务共享
2. **429 退避**：被限流时自动等待重试，优先读 `Retry-After`，无则指数退避
3. **网络错误退避**：连接超时等也自动退避重试

**配置建议**：
- `MAX_LLM_CONCURRENCY`：根据 LLM API 的并发上限设置，建议从 4 开始测试
- 如果 API 文档标注了 RPM（每分钟请求数）限制，还需考虑时间窗口限流（当前方案未实现，见 7.2 限制）

#### 5.2.2 数据库连接池

**问题**：多用户并发更新进度时，数据库连接可能不够。

**解决方案**：
- 检查 MySQL 连接池配置，确保 `pool_size` ≥ `MAX_LLM_CONCURRENCY + 预留`
- 进度更新使用短事务：`update_task` 只更新一行，执行很快
- 可考虑批量更新：不是每页完成都更新进度，而是每 2-3 页或每 5 秒更新一次

**具体改动**：
```python
# app/infrastructure/database/mysql.py（或对应文件）
# 确保连接池配置：
# pool_size = max(MAX_LLM_CONCURRENCY + 4, 10)
# max_overflow = 10
```

#### 5.2.3 内存占用

**问题**：每个并发任务在内存中持有 SVG 内容，多用户时内存可能紧张。

**解决方案**：
- SVG 内容在 `_process_one_page` 中读取后用完即释放（局部变量，方法结束自动回收）
- 全局信号量限制了同时执行的 LLM 请求数，间接限制了同时活跃的页面数
- `svg_final/` 目录中的文件写入磁盘后不再在内存中持有
- 如果 SVG 特别大（>1MB），可在读取后立即写入临时文件，处理时再读

**监控**：
```python
# 在 _process_one_page 开头记录
import resource
mem_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
# ... 处理 ...
mem_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
if mem_after - mem_before > 50 * 1024:  # 50MB
    logger.warning("页面 %s 内存增长较大: %.1fMB", page_no, (mem_after - mem_before) / 1024)
```

#### 5.2.4 FTP 写入瓶颈

**问题**：mock_ftp 模式下多任务同时写磁盘，可能 I/O 瓶颈。

**解决方案**：
- mock_ftp 模式下写入是本地文件操作，磁盘 I/O 通常不是瓶颈（SSD 可承受高并发写入）
- 不同任务写入不同目录（`mock_ftp/slides_gen_server/tasks/{task_id}/`），无锁竞争
- 真实 FTP 模式下，FTP 服务器有自己的连接限制，需确认 FTP 连接池配置
- 如果确实出现 I/O 瓶颈，可将 FTP 上传改为异步队列（当前方案不实现，观察后再决定）

#### 5.2.5 进度更新竞争

**问题**：多线程同时更新同一任务的进度字段。

**解决方案**：
- 使用 `threading.Lock` 保护计数器（已在设计中实现）
- 数据库更新是原子操作（单行 UPDATE），MySQL 行锁保证一致性
- 不同任务更新不同行，无竞争

---

## 6. 限制与注意事项

### 6.1 LLM API 并发限制

- 全局信号量控制并发请求数，但不控制请求频率（RPM）
- 如果 LLM API 有 RPM 限制（如 60 次/分钟），需要额外实现时间窗口限流
- 当前方案只控制并发数，假设 API 限制是并发数而非 RPM
- 如果遇到 RPM 限制，429 退避机制会自动处理，但效率会降低

### 6.2 页面顺序

- 并发处理后页面完成顺序不固定
- 最终导出 PPTX 时按文件名排序（`slide_1.svg`, `slide_2.svg`, ...）
- `svg_final/` 目录中的文件名保持原始模板文件名，天然有序

### 6.3 停止任务

- 停止请求通过数据库 `stop_requested` 字段传递
- 每个 worker 在开始处理前检查此字段
- 已在执行中的 LLM 请求无法立即中断，需等当前请求返回后检查
- `ThreadPoolExecutor.shutdown(cancel_futures=True)` 可取消尚未开始的任务

### 6.4 错误隔离

- 单页失败不影响其他页
- 规划失败回退启发式，生成失败标记 `failed` 跳过
- `as_completed` 中 `future.result()` 抛出的异常需要捕获，避免影响其他 Future 的收集

### 6.5 断点续做

- 已完成的页面（`PAGE_STATUS_COMPLETED`）在并发开始前检查，直接跳过
- 并发提交时不会为已完成页面创建任务
- 如果任务中途失败重启，已完成页面不会重复处理

### 6.6 信号量与线程池的关系

- 线程池 `max_workers=total_pages` 意味着所有页面同时提交
- 但 LLM 调用前需要 `semaphore.acquire()`，实际并发受全局信号量控制
- 非 LLM 操作（文件读写、校验、FTP 上传）不受信号量限制，可以真正并行
- 这意味着：如果 `MAX_LLM_CONCURRENCY=4`，模板有 15 页，则最多 4 页同时在等 LLM 响应，其他页在做文件操作或等待信号量

### 6.7 httpx2 客户端线程安全

- 当前每次 `_call_llm` 创建新的 `httpx2.Client` 实例，无共享问题
- 如果未来优化为复用 Client 实例，`httpx2.Client` 本身是线程安全的，但连接池可能成为瓶颈
- 建议保持当前每次创建新 Client 的方式，简单可靠

---

## 7. 配置建议

### 7.1 环境变量

```env
# LLM 全局并发控制
MAX_LLM_CONCURRENCY=8          # 全局 LLM 最大并发数，建议 4-16

# LLM 限流退避
LLM_RATE_LIMIT_MAX_RETRIES=5   # 429/网络错误最大重试次数
LLM_RATE_LIMIT_BASE_DELAY=1.0  # 退避基础延迟（秒）
LLM_RATE_LIMIT_MAX_DELAY=60.0  # 退避最大延迟（秒）
```

### 7.2 配置调优建议

| 场景 | MAX_LLM_CONCURRENCY | 说明 |
|------|---------------------|------|
| 单用户、小模板（≤10页） | 4-6 | 充分利用并发 |
| 多用户、大模板（>15页） | 8-16 | 需确认 API 并发上限 |
| API 限制严格 | 2-4 | 保守设置，避免频繁 429 |
| 本地开发调试 | 2 | 减少对开发环境的压力 |

### 7.3 监控建议

- 在日志中记录每页规划和生成的开始/结束时间
- 记录信号量等待时间（acquire 前后时间差）
- 记录 429 重试次数和退避时间
- 记录线程池活跃线程数

```python
# 信号量等待时间监控
wait_start = time.time()
semaphore.acquire()
wait_time = time.time() - wait_start
if wait_time > 5.0:
    logger.warning("LLM 信号量等待 %.1fs，可能并发过高", wait_time)
```

---

## 8. 实现步骤（全部完成）

1. ✅ **新增 `app/infrastructure/llm/concurrency.py`**：全局信号量管理
2. ✅ **修改 `app/core/config.py`**：新增 4 个配置字段
3. ✅ **修改 `.env`**：新增 4 个环境变量
4. ✅ **修改 `app/infrastructure/llm/openai_like_client.py`**：`_call_llm` 加入信号量 + 429 退避 + 网络错误退避
5. ✅ **修改 `app/services/bootstrap.py`**：初始化全局信号量
6. ✅ **修改 `app/services/orchestration_service.py`**：`run_task` 改为并发模式，提取 `_process_one_page` 和 `_update_progress`
7. ✅ **修改 `app/services/slide_generation_service.py`**：重构 `plan_pages` 为 `plan_single_page`，供并发调用
8. ✅ **补充测试**：`tests/test_concurrency.py` 覆盖信号量、429 退避、网络错误退避、退避计算
9. ✅ **更新文档**：readme.md、development_notes.md、fastapi_service_architecture.md、concurrency_design.md

---

## 9. 总结

**方案核心**：全局信号量 + 统一队列 + 429 退避

**优势**：
- 实现简单：一个信号量 + 每页一个 Future
- 性能最优：规划完直接生成，无等待空窗
- 多用户公平：全局统一排队，不偏袒任何任务
- 限流自适应：优先读 Retry-After，无则指数退避

**限制**：
- 不控制 RPM（只控制并发数），如需 RPM 限制需额外实现
- 停止任务有延迟（需等当前 LLM 请求返回）
- 页面完成顺序不固定（最终按文件名排序解决）
