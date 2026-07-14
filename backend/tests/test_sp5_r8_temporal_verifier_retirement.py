from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import time
from typing import Any

import pytest

from metascan.pipeline.command_pipeline import CommandPipeline


class ObservableConcurrentFuture(concurrent.futures.Future):
    def __init__(self) -> None:
        super().__init__()
        self.exception_calls = 0
        self.result_calls = 0

    def exception(self, timeout: float | None = None):
        self.exception_calls += 1
        return super().exception(timeout)

    def result(self, timeout: float | None = None):
        self.result_calls += 1
        return super().result(timeout)


class Gateway:
    def __init__(self, source: ObservableConcurrentFuture) -> None:
        self.source = source
        self.calls = 0
        self.active = 0
        self.max_active = 0

    def verify(self, *args: Any) -> ObservableConcurrentFuture:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.source.add_done_callback(lambda future: setattr(self, "active", self.active - 1))
        return self.source


def pipeline_for(gateway: Any) -> CommandPipeline:
    pipeline = CommandPipeline.__new__(CommandPipeline)
    pipeline._gateway = gateway
    return pipeline


async def callback_turns(count: int = 4) -> None:
    for _ in range(count):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_same_turn_source_exception_and_timeout_retires_source(monkeypatch: pytest.MonkeyPatch) -> None:
    source = ObservableConcurrentFuture()
    gateway = Gateway(source)

    async def boundary(awaitable: Any, timeout: float) -> Any:
        source.set_exception(RuntimeError("same turn"))
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", boundary)
    result = await pipeline_for(gateway)._temporal_verify("command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=1.0)
    assert result[0] is None
    assert gateway.calls == 1
    assert gateway.max_active == 1
    assert source.exception_calls == 1
    assert source.result_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("completion", "expected"), [({"positionExists": True}, True), (RuntimeError("boundary"), None)])
async def test_timeout_inspects_completed_source_once(
    monkeypatch: pytest.MonkeyPatch, completion: dict[str, Any] | Exception, expected: bool | None
) -> None:
    source = ObservableConcurrentFuture()
    gateway = Gateway(source)

    async def boundary(awaitable: Any, timeout: float) -> Any:
        if isinstance(completion, Exception):
            source.set_exception(completion)
        else:
            source.set_result(completion)
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", boundary)
    result = await pipeline_for(gateway)._temporal_verify("command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=1.0)
    assert result[0] is expected
    assert gateway.calls == 1
    assert source.exception_calls == 1
    assert source.result_calls == (1 if expected is True else 0)


@pytest.mark.asyncio
async def test_source_timeout_before_deadline_retires_then_retries_at_cadence() -> None:
    first = ObservableConcurrentFuture()
    second = ObservableConcurrentFuture()
    calls: list[float] = []
    loop = asyncio.get_running_loop()

    class ScriptedGateway:
        def verify(self, *args: Any) -> ObservableConcurrentFuture:
            calls.append(time.perf_counter())
            return first if len(calls) == 1 else second

    loop.call_later(0.005, first.set_exception, asyncio.TimeoutError())
    loop.call_later(0.04, second.set_result, {"positionExists": True})
    result = await pipeline_for(ScriptedGateway())._temporal_verify(
        "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=0.2, poll_interval_ms=30
    )
    assert result[0] is True
    assert len(calls) == 2
    assert result[4][1] - result[4][0] >= 0.025
    assert calls[1] - calls[0] >= 0.025, f"call_times={result[4]!r} observed={calls!r}"
    assert first.exception_calls == 1
    assert second.exception_calls == 1
    assert second.result_calls == 1


@pytest.mark.asyncio
async def test_early_sleep_wake_cannot_submit_before_attempt_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = 10.0
    calls: list[float] = []
    sleeps: list[float] = []
    async def early_sleep(delay: float) -> None:
        nonlocal clock
        sleeps.append(delay)
        clock += delay / 2 if len(sleeps) == 1 else delay

    class ScriptedGateway:
        def verify(self, *args: Any) -> ObservableConcurrentFuture:
            calls.append(clock)
            future = ObservableConcurrentFuture()
            if len(calls) == 1:
                future.set_exception(RuntimeError("retry"))
            else:
                future.set_result({"positionExists": True})
            return future

    monkeypatch.setattr(time, "perf_counter", lambda: clock)
    monkeypatch.setattr(asyncio, "sleep", early_sleep)
    result = await pipeline_for(ScriptedGateway())._temporal_verify(
        "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=1.0, poll_interval_ms=30
    )
    assert result[0] is True
    assert calls == [10.0, 10.03]
    assert len(sleeps) > 1
    assert "time.perf_counter" in inspect.getsource(CommandPipeline._temporal_verify)


@pytest.mark.asyncio
async def test_pending_source_remains_single_active_until_deadline_then_late_exception_is_consumed() -> None:
    source = ObservableConcurrentFuture()
    gateway = Gateway(source)
    result = await pipeline_for(gateway)._temporal_verify(
        "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=0.04, poll_interval_ms=10
    )
    assert result[0] is None
    assert gateway.calls == 1
    assert gateway.max_active == 1
    source.set_exception(RuntimeError("late"))
    await callback_turns()
    assert source.exception_calls == 1


@pytest.mark.asyncio
async def test_cancellation_propagates_then_late_source_exception_is_consumed() -> None:
    source = ObservableConcurrentFuture()
    gateway = Gateway(source)
    task = asyncio.create_task(
        pipeline_for(gateway)._temporal_verify(
            "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=1.0, poll_interval_ms=30
        )
    )
    while gateway.calls == 0:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gateway.calls == 1
    source.set_exception(RuntimeError("late"))
    await callback_turns()
    assert source.exception_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("completion", "expected_calls"),
    [(RuntimeError("source"), 2), ({"positionExists": True}, 1)],
)
async def test_completed_source_is_consumed_then_retried_at_cadence_when_needed(
    completion: Exception | dict[str, Any], expected_calls: int
) -> None:
    first = ObservableConcurrentFuture()
    second = ObservableConcurrentFuture()
    loop = asyncio.get_running_loop()
    calls: list[float] = []

    class ScriptedGateway:
        def verify(self, *args: Any) -> ObservableConcurrentFuture:
            calls.append(time.perf_counter())
            return first if len(calls) == 1 else second

    if isinstance(completion, Exception):
        loop.call_later(0.005, first.set_exception, completion)
        loop.call_later(0.04, second.set_result, {"positionExists": True})
    else:
        loop.call_later(0.005, first.set_result, completion)
    result = await pipeline_for(ScriptedGateway())._temporal_verify(
        "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=0.2, poll_interval_ms=30
    )
    assert result[0] is True
    assert len(calls) == expected_calls
    if expected_calls == 2:
        assert calls[1] - calls[0] >= 0.025
    assert first.exception_calls == 1
    assert first.result_calls == (1 if expected_calls == 1 else 0)
