"""TaskRunner 回归测试：submit 不能依赖调用方的事件循环生命周期。

原实现用 `asyncio.create_task(to_thread(...))`，任务挂在提交时所在线程的
事件循环上——当 submit 发生在某个即将关闭的临时 loop（子任务收尾触发
下一个任务）中时，任务对象会随宿主 loop 关闭被取消，job 永远得不到执行。
"""

from __future__ import annotations

import asyncio
import threading

from app.infrastructure.tasking.runner import TaskRunner


def test_submit_from_transient_loop_still_runs_job():
    """在即将关闭的临时事件循环里 submit，job 也必须真正执行。"""
    runner = TaskRunner()
    done = threading.Event()

    async def job() -> None:
        done.set()

    async def outer() -> None:
        runner.submit("t1", lambda: job())

    # outer 的 loop 在 submit 后立即关闭；旧实现下 job 会随 loop 一起死掉
    asyncio.run(outer())
    assert done.wait(timeout=5), "submit 的 job 未执行——任务随宿主 loop 关闭被丢弃"


def test_submit_without_event_loop():
    """完全不在事件循环里的普通线程也能 submit。"""
    runner = TaskRunner()
    done = threading.Event()

    async def job() -> None:
        done.set()

    runner.submit("t2", lambda: job())
    assert done.wait(timeout=5)


def test_submit_same_task_id_not_duplicated():
    """运行中的 task_id 重复 submit 被忽略。"""
    import time

    runner = TaskRunner()
    gate = threading.Event()
    calls: list[str] = []

    async def job() -> None:
        calls.append("run")
        gate.wait(timeout=2)

    runner.submit("t3", lambda: job())
    for _ in range(200):
        if runner.is_running("t3") and calls:
            break
        time.sleep(0.01)
    assert calls == ["run"], "job 未启动"
    runner.submit("t3", lambda: job())  # 重复提交应被忽略
    gate.set()
    for _ in range(200):
        if not runner.is_running("t3"):
            break
        time.sleep(0.01)
    assert calls == ["run"]
