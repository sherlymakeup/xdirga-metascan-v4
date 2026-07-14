from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
from typing import Any, Callable

import pytest

from metascan.pipeline.command_pipeline import CommandPipeline


class ObservableFuture(concurrent.futures.Future):
    def __init__(self, markers: list[str]) -> None:
        super().__init__()
        self.markers = markers
        self.exception_calls = 0
        self.result_calls = 0

    def exception(self, timeout: float | None = None):
        self.exception_calls += 1
        self.markers.append("source consumed")
        return super().exception(timeout)

    def result(self, timeout: float | None = None):
        self.result_calls += 1
        return super().result(timeout)


class Gateway:
    def __init__(self, source: ObservableFuture) -> None:
        self.source = source
        self.calls = 0
        self.active = 0
        self.max_active = 0

    def verify(self, *args: Any) -> ObservableFuture:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.source.add_done_callback(lambda _: setattr(self, "active", self.active - 1))
        return self.source


def pipeline_for(gateway: Gateway) -> CommandPipeline:
    pipeline = CommandPipeline.__new__(CommandPipeline)
    pipeline._gateway = gateway
    return pipeline


async def run(gateway: Gateway) -> tuple[bool | None, str | None, dict[str, Any], int, list[float]]:
    return await pipeline_for(gateway)._temporal_verify(
        "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=1.0, poll_interval_ms=30
    )


def block_notifications(monkeypatch: pytest.MonkeyPatch, markers: list[str]) -> list[tuple[Callable[..., Any], tuple[Any, ...]]]:
    loop = asyncio.get_running_loop()
    queued: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []

    def enqueue(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        markers.append("outcome stored")
        queued.append((callback, args))
        markers.append("notification pending")

    monkeypatch.setattr(loop, "call_soon_threadsafe", enqueue)
    return queued


@pytest.mark.asyncio
async def test_a_timeout_reads_success_handoff_before_ready_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    markers: list[str] = []
    source = ObservableFuture(markers)
    gateway = Gateway(source)
    queued = block_notifications(monkeypatch, markers)

    async def boundary(awaitable: Any, timeout: float) -> Any:
        source.set_result({"positionExists": True})
        assert markers == ["source consumed", "outcome stored", "notification pending"]
        assert not awaitable.done()
        markers.append("timeout")
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", boundary)
    result = await run(gateway)
    markers.append("verdict")
    assert result[0] is True
    assert markers == ["source consumed", "outcome stored", "notification pending", "timeout", "verdict"]
    assert len(queued) == 1
    assert gateway.calls == 1
    assert gateway.max_active == 1
    assert source.exception_calls == 1
    assert source.result_calls == 1


@pytest.mark.asyncio
async def test_b_timeout_reads_exception_handoff_before_ready_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    markers: list[str] = []
    source = ObservableFuture(markers)
    gateway = Gateway(source)
    queued = block_notifications(monkeypatch, markers)

    async def boundary(awaitable: Any, timeout: float) -> Any:
        source.set_exception(RuntimeError("boundary"))
        assert markers == ["source consumed", "outcome stored", "notification pending"]
        assert not awaitable.done()
        markers.append("timeout")
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", boundary)
    result = await run(gateway)
    markers.append("verdict")
    assert result[0] is None
    assert markers == ["source consumed", "outcome stored", "notification pending", "timeout", "verdict"]
    assert len(queued) == 1
    assert gateway.calls == 1
    assert gateway.max_active == 1
    assert source.exception_calls == 1
    assert source.result_calls == 0


@pytest.mark.asyncio
async def test_c_cancellation_propagates_with_populated_handoff_and_ready_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    markers: list[str] = []
    source = ObservableFuture(markers)
    gateway = Gateway(source)
    queued = block_notifications(monkeypatch, markers)

    async def cancelled(awaitable: Any, timeout: float) -> Any:
        source.set_result({"positionExists": True})
        assert markers == ["source consumed", "outcome stored", "notification pending"]
        assert not awaitable.done()
        markers.append("cancelled")
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "wait_for", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await run(gateway)
    assert markers == ["source consumed", "outcome stored", "notification pending", "cancelled"]
    assert len(queued) == 1
    assert gateway.calls == 1
    assert source.exception_calls == 1
    assert source.result_calls == 1


@pytest.mark.asyncio
async def test_d_cancelled_source_is_consumed_as_ordinary_exception() -> None:
    markers: list[str] = []
    source = ObservableFuture(markers)
    gateway = Gateway(source)
    source.cancel()
    result = await run(gateway)
    assert result[0] is None
    assert gateway.calls >= 1
    assert source.exception_calls == gateway.calls
    assert source.result_calls == 0
    assert "BaseException" not in inspect.getsource(CommandPipeline._temporal_verify)


@pytest.mark.asyncio
async def test_e_late_source_exception_is_consumed_when_loop_notification_is_unavailable(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    markers: list[str] = []
    source = ObservableFuture(markers)
    gateway = Gateway(source)
    task = asyncio.create_task(run(gateway))
    while gateway.calls == 0:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "is_closed", lambda: True)
    monkeypatch.setattr(loop, "call_soon_threadsafe", lambda *args: (_ for _ in ()).throw(RuntimeError("Event loop is closed")))
    source.set_exception(RuntimeError("late"))
    assert source.exception_calls == 1
    assert source.result_calls == 0
    assert "exception calling callback" not in caplog.text
