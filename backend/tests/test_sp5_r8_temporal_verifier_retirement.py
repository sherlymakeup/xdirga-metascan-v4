from __future__ import annotations

import asyncio
import concurrent.futures
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


class ObservableAsyncFuture(asyncio.Future):
    def __init__(self) -> None:
        super().__init__()
        self.exception_calls = 0

    def exception(self):
        self.exception_calls += 1
        return super().exception()


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


def pipeline_for(gateway: Gateway) -> CommandPipeline:
    pipeline = CommandPipeline.__new__(CommandPipeline)
    pipeline._gateway = gateway
    return pipeline


async def callback_turns(count: int = 4) -> None:
    for _ in range(count):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_same_turn_source_exception_and_timeout_retires_every_future(monkeypatch: pytest.MonkeyPatch) -> None:
    source = ObservableConcurrentFuture()
    wrapped = ObservableAsyncFuture()
    shield = ObservableAsyncFuture()
    loop = asyncio.get_running_loop()
    contexts: list[dict[str, Any]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda current, context: contexts.append(context))

    def wrap(future: concurrent.futures.Future) -> asyncio.Future:
        def transfer(done: concurrent.futures.Future) -> None:
            error = done.exception()
            if error is not None:
                wrapped.set_exception(error)
            else:
                wrapped.set_result(done.result())

        future.add_done_callback(lambda done: loop.call_soon(transfer, done))
        return wrapped

    def protect(future: asyncio.Future) -> asyncio.Future:
        def transfer(done: asyncio.Future) -> None:
            error = done.exception()
            if error is not None:
                shield.set_exception(error)
            else:
                shield.set_result(done.result())

        future.add_done_callback(lambda done: loop.call_soon(transfer, done))
        return shield

    async def boundary(awaitable: Any, timeout: float) -> Any:
        source.set_exception(RuntimeError("same turn"))
        await callback_turns(2)
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wrap_future", wrap)
    monkeypatch.setattr(asyncio, "shield", protect)
    monkeypatch.setattr(asyncio, "wait_for", boundary)
    gateway = Gateway(source)
    try:
        result = await pipeline_for(gateway)._temporal_verify("command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=1.0)
        await callback_turns()
        assert result[0] is None
        assert gateway.calls == 1
        assert gateway.max_active == 1
        assert source.exception_calls == 1
        assert wrapped.exception_calls == 1
        assert shield.exception_calls == 1
        assert contexts == []
    finally:
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("completion", "expected"),
    [({"positionExists": True}, True), (RuntimeError("boundary"), None)],
)
async def test_cancelled_waiting_inspects_completed_wrapped_once(
    monkeypatch: pytest.MonkeyPatch, completion: dict[str, Any] | Exception, expected: bool | None
) -> None:
    source = ObservableConcurrentFuture()
    wrapped = ObservableAsyncFuture()
    loop = asyncio.get_running_loop()
    contexts: list[dict[str, Any]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda current, context: contexts.append(context))

    def wrap(future: concurrent.futures.Future) -> asyncio.Future:
        def transfer(done: concurrent.futures.Future) -> None:
            error = done.exception()
            if error is not None:
                wrapped.set_exception(error)
            else:
                wrapped.set_result(done.result())

        future.add_done_callback(lambda done: loop.call_soon(transfer, done))
        return wrapped

    waiting = ObservableAsyncFuture()

    async def boundary(awaitable: asyncio.Future, timeout: float) -> Any:
        if isinstance(completion, Exception):
            source.set_exception(completion)
        else:
            source.set_result(completion)
        await callback_turns(1)
        assert wrapped.done()
        assert not awaitable.done()
        awaitable.cancel()
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wrap_future", wrap)
    monkeypatch.setattr(asyncio, "shield", lambda future: waiting)
    monkeypatch.setattr(asyncio, "wait_for", boundary)
    gateway = Gateway(source)
    try:
        result = await pipeline_for(gateway)._temporal_verify("command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=1.0)
        await callback_turns()
        assert result[0] is expected
        assert gateway.calls == 1
        assert source.exception_calls == 1
        assert source.result_calls == (1 if expected is True else 0)
        assert wrapped.exception_calls == 1
        assert contexts == []
    finally:
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_source_timeout_before_deadline_retires_then_retries_at_cadence() -> None:
    first = ObservableConcurrentFuture()
    second = ObservableConcurrentFuture()
    calls: list[float] = []
    loop = asyncio.get_running_loop()

    class ScriptedGateway:
        def verify(self, *args: Any) -> ObservableConcurrentFuture:
            calls.append(loop.time())
            return first if len(calls) == 1 else second

    loop.call_later(0.005, first.set_exception, asyncio.TimeoutError())
    loop.call_later(0.04, second.set_result, {"positionExists": True})
    result = await pipeline_for(ScriptedGateway())._temporal_verify(
        "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=0.2, poll_interval_ms=30
    )
    assert result[0] is True
    assert len(calls) == 2
    assert calls[1] - calls[0] >= 0.025
    assert first.exception_calls == 1
    assert second.exception_calls == 1
    assert second.result_calls == 1


@pytest.mark.asyncio
async def test_wrap_failure_keeps_pending_source_active_until_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    source = ObservableConcurrentFuture()
    loop = asyncio.get_running_loop()
    contexts: list[dict[str, Any]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda current, context: contexts.append(context))
    gateway = Gateway(source)
    monkeypatch.setattr(asyncio, "wrap_future", lambda future: (_ for _ in ()).throw(RuntimeError("wrap failed")))
    try:
        result = await pipeline_for(gateway)._temporal_verify(
            "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=0.04, poll_interval_ms=10
        )
        assert result[0] is None
        assert gateway.calls == 1
        assert gateway.max_active == 1
        source.set_exception(RuntimeError("late"))
        await callback_turns()
        assert source.exception_calls == 1
        assert contexts == []
    finally:
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_wrap_failure_cancellation_drains_late_source(monkeypatch: pytest.MonkeyPatch) -> None:
    source = ObservableConcurrentFuture()
    gateway = Gateway(source)
    loop = asyncio.get_running_loop()
    contexts: list[dict[str, Any]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda current, context: contexts.append(context))
    monkeypatch.setattr(asyncio, "wrap_future", lambda future: (_ for _ in ()).throw(RuntimeError("wrap failed")))
    try:
        task = asyncio.create_task(
            pipeline_for(gateway)._temporal_verify(
                "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=1.0, poll_interval_ms=30
            )
        )
        await callback_turns()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gateway.calls == 1
        source.set_exception(RuntimeError("late"))
        await callback_turns()
        assert source.exception_calls == 1
        assert contexts == []
    finally:
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("completion", "expected", "expected_calls"),
    [(RuntimeError("source"), True, 2), ({"positionExists": True}, True, 1)],
)
async def test_wrap_failure_consumes_completed_source(
    monkeypatch: pytest.MonkeyPatch,
    completion: Exception | dict[str, Any],
    expected: bool,
    expected_calls: int,
) -> None:
    first = ObservableConcurrentFuture()
    second = ObservableConcurrentFuture()
    loop = asyncio.get_running_loop()
    calls: list[float] = []

    class ScriptedGateway:
        def verify(self, *args: Any) -> ObservableConcurrentFuture:
            calls.append(loop.time())
            return first if len(calls) == 1 else second

    monkeypatch.setattr(asyncio, "wrap_future", lambda future: (_ for _ in ()).throw(RuntimeError("wrap failed")))
    if isinstance(completion, Exception):
        loop.call_later(0.005, first.set_exception, completion)
        loop.call_later(0.04, second.set_result, {"positionExists": True})
    else:
        loop.call_later(0.005, first.set_result, completion)
    result = await pipeline_for(ScriptedGateway())._temporal_verify(
        "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=0.2, poll_interval_ms=30
    )
    assert result[0] is expected
    assert len(calls) == expected_calls
    if expected_calls == 2:
        assert calls[1] - calls[0] >= 0.025
    assert first.exception_calls == 1
    assert first.result_calls == (1 if expected_calls == 1 else 0)


@pytest.mark.asyncio
async def test_pending_at_deadline_returns_and_late_exception_retires_every_future(monkeypatch: pytest.MonkeyPatch) -> None:
    source = ObservableConcurrentFuture()
    wrapped = ObservableAsyncFuture()
    shield = ObservableAsyncFuture()
    loop = asyncio.get_running_loop()
    contexts: list[dict[str, Any]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda current, context: contexts.append(context))

    def wrap(future: concurrent.futures.Future) -> asyncio.Future:
        def transfer(done: concurrent.futures.Future) -> None:
            error = done.exception()
            if error is not None:
                wrapped.set_exception(error)
            else:
                wrapped.set_result(done.result())

        future.add_done_callback(lambda done: loop.call_soon(transfer, done))
        return wrapped

    def protect(future: asyncio.Future) -> asyncio.Future:
        def transfer(done: asyncio.Future) -> None:
            error = done.exception()
            if error is not None:
                shield.set_exception(error)
            else:
                shield.set_result(done.result())

        future.add_done_callback(lambda done: loop.call_soon(transfer, done))
        return shield

    async def boundary(awaitable: Any, timeout: float) -> Any:
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wrap_future", wrap)
    monkeypatch.setattr(asyncio, "shield", protect)
    monkeypatch.setattr(asyncio, "wait_for", boundary)
    gateway = Gateway(source)
    try:
        started = loop.time()
        result = await pipeline_for(gateway)._temporal_verify("command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=0.05)
        assert loop.time() - started < 0.04
        assert result[0] is None
        assert gateway.calls == 1
        assert gateway.max_active == 1
        source.set_exception(RuntimeError("late"))
        await callback_turns()
        assert source.exception_calls == 1
        assert wrapped.exception_calls == 1
        assert shield.exception_calls == 1
        assert contexts == []
    finally:
        loop.set_exception_handler(previous_handler)
