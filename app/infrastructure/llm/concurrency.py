"""全局 LLM 并发信号量管理。

所有任务的 LLM 请求（规划 + 生成）共享同一个信号量，
由 MAX_LLM_CONCURRENCY 环境变量控制全局并发上限。
"""
from __future__ import annotations

import threading

_global_semaphore: threading.Semaphore | None = None
_init_lock = threading.Lock()


def init_global_semaphore(max_concurrency: int) -> None:
    """在应用启动时调用（bootstrap.build_services 中），初始化全局信号量。

    如果已经初始化过，则跳过（幂等）。
    """
    global _global_semaphore
    with _init_lock:
        if _global_semaphore is None:
            _global_semaphore = threading.Semaphore(max_concurrency)


def get_global_semaphore() -> threading.Semaphore:
    """获取全局信号量实例。如果未初始化则抛出异常。"""
    if _global_semaphore is None:
        raise RuntimeError("全局信号量未初始化，请先调用 init_global_semaphore()")
    return _global_semaphore


def reset_global_semaphore() -> None:
    """重置信号量（仅用于测试）。"""
    global _global_semaphore
    with _init_lock:
        _global_semaphore = None
