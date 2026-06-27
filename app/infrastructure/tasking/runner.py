from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable


class TaskRunner:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def is_running(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        return bool(task and not task.done())

    def submit(self, task_id: str, job: Callable[[], Awaitable[None]]) -> None:
        existing = self._tasks.get(task_id)
        if existing and not existing.done():
            return
        runner = asyncio.create_task(
            asyncio.to_thread(self._run_job, job),
            name=f"slides-task-{task_id}",
        )
        runner.add_done_callback(lambda _: self._tasks.pop(task_id, None))
        self._tasks[task_id] = runner

    @staticmethod
    def _run_job(job: Callable[[], Awaitable[None]]) -> None:
        result = job()
        if inspect.isawaitable(result):
            asyncio.run(result)
