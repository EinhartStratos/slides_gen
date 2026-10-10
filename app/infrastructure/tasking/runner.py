from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Awaitable, Callable


class TaskRunner:
    """把协程型 job 放到独立线程里跑（线程内自建 asyncio.run 循环）。

    不能用 asyncio.create_task：submit 的调用点可能在即将关闭的临时
    事件循环里（如子任务收尾时触发下一个任务），任务对象会随宿主 loop
    关闭被一并取消，表现为"子任务已创建但永远 pending"。
    独立线程不依赖任何现存 loop，天然免疫该竞态。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def is_running(self, task_id: str) -> bool:
        with self._lock:
            thread = self._tasks.get(task_id)
            return bool(thread and thread.is_alive())

    def submit(self, task_id: str, job: Callable[[], Awaitable[None]]) -> None:
        with self._lock:
            existing = self._tasks.get(task_id)
            if existing and existing.is_alive():
                return

            def _wrapper() -> None:
                try:
                    self._run_job(job)
                finally:
                    with self._lock:
                        self._tasks.pop(task_id, None)

            thread = threading.Thread(
                target=_wrapper,
                name=f"slides-task-{task_id}",
                daemon=True,
            )
            self._tasks[task_id] = thread
            thread.start()

    @staticmethod
    def _run_job(job: Callable[[], Awaitable[None]]) -> None:
        result = job()
        if inspect.isawaitable(result):
            asyncio.run(result)
