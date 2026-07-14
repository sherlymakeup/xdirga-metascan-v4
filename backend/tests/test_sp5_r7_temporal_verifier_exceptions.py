from __future__ import annotations

import asyncio
import concurrent.futures
import time
from types import SimpleNamespace
from typing import Any

import pytest

from metascan.pipeline.command_pipeline import CommandPipeline


class ScriptedGateway:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[float] = []
        self.active = 0
        self.max_active = 0

    def verify(self, *args: Any) -> concurrent.futures.Future:
        loop = asyncio.get_running_loop()
        self.calls.append(loop.time())
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        delay, value = item if isinstance(item, tuple) else (0.0, item)
        future: concurrent.futures.Future = concurrent.futures.Future()
        self.active += 1
        self.max_active = max(self.max_active, self.active)

        def finish() -> None:
            self.active -= 1
            if isinstance(value, Exception):
                future.set_exception(value)
            else:
                future.set_result(value)

        loop.call_later(delay, finish)
        return future


def pipeline_for(gateway: Any) -> CommandPipeline:
    pipeline = CommandPipeline.__new__(CommandPipeline)
    pipeline._gateway = gateway
    return pipeline


async def run(gateway: Any, *, timeout: float = 0.25, interval_ms: int = 30):
    return await pipeline_for(gateway)._temporal_verify(
        "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=timeout, poll_interval_ms=interval_ms
    )


@pytest.mark.asyncio
async def test_a_completed_exception_is_consumed_once_then_success_retries_at_cadence() -> None:
    gateway = ScriptedGateway([(0.005, RuntimeError("one")), (0.005, {"positionExists": True})])
    result = await run(gateway)
    assert result[0] is True
    assert len(gateway.calls) == 2
    assert gateway.calls[1] - gateway.calls[0] >= 0.025


@pytest.mark.asyncio
async def test_b_multiple_async_exceptions_then_success_without_spin() -> None:
    gateway = ScriptedGateway([(0.001, RuntimeError("one")), (0.001, RuntimeError("two")), (0.001, {"positionExists": True})])
    beats = 0

    async def heartbeat() -> None:
        nonlocal beats
        while len(gateway.calls) < 3:
            beats += 1
            await asyncio.sleep(0.003)

    pulse = asyncio.create_task(heartbeat())
    result = await run(gateway)
    await pulse
    assert result[0] is True
    assert beats >= 6
    assert gateway.max_active == 1


@pytest.mark.asyncio
async def test_c_async_exceptions_until_deadline_use_full_budget_without_call_storm() -> None:
    gateway = ScriptedGateway([(0.001, RuntimeError(str(index))) for index in range(20)])
    started = time.monotonic()
    result = await run(gateway, timeout=0.14, interval_ms=30)
    elapsed = time.monotonic() - started
    assert result[0] is None
    assert 0.12 <= elapsed < 0.25
    assert 3 <= len(gateway.calls) <= 5
    assert gateway.max_active == 1


@pytest.mark.asyncio
async def test_d_synchronous_verify_submission_failure_retries_at_cadence() -> None:
    gateway = ScriptedGateway([RuntimeError("submit one"), RuntimeError("submit two"), {"positionExists": True}])
    result = await run(gateway)
    assert result[0] is True
    assert len(gateway.calls) == 3
    assert all(right - left >= 0.025 for left, right in zip(gateway.calls, gateway.calls[1:]))


@pytest.mark.asyncio
async def test_d_type_error_from_modern_verify_is_one_submission_then_cadence_retry() -> None:
    gateway = ScriptedGateway([TypeError("implementation failure"), {"positionExists": True}])
    result = await run(gateway)
    assert result[0] is True
    assert len(gateway.calls) == 2
    assert gateway.calls[1] - gateway.calls[0] >= 0.025


@pytest.mark.asyncio
async def test_d_unknown_signature_invokes_modern_once() -> None:
    class Verify:
        calls: list[tuple[Any, ...]] = []

        @property
        def __signature__(self) -> Any:
            raise ValueError("unknown signature")

        def __call__(self, *args: Any) -> concurrent.futures.Future:
            self.calls.append(args)
            future: concurrent.futures.Future = concurrent.futures.Future()
            future.set_result({"positionExists": True})
            return future

    verify = Verify()
    gateway = SimpleNamespace(verify=verify)
    result = await run(gateway)
    assert result[0] is True
    assert verify.calls == [("command", "INTERNAL_ENTRY_MARKET", None, {})]


@pytest.mark.asyncio
async def test_d_declared_one_argument_legacy_verify_receives_target() -> None:
    class Gateway:
        calls: list[str | None] = []

        def verify(self, target: str | None) -> concurrent.futures.Future:
            self.calls.append(target)
            future: concurrent.futures.Future = concurrent.futures.Future()
            future.set_result({"positionExists": True})
            return future

    gateway = Gateway()
    result = await run(gateway)
    assert result[0] is True
    assert gateway.calls == [None]


@pytest.mark.asyncio
async def test_e_same_turn_completed_result_is_inspected_before_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    source: concurrent.futures.Future = concurrent.futures.Future()

    class Gateway:
        calls = 0

        def verify(self, command_id: str, kind: str, target: str | None, payload: dict[str, Any]) -> concurrent.futures.Future:
            self.calls += 1
            return source

    async def boundary(awaitable: Any, timeout: float) -> Any:
        source.set_result({"positionExists": True})
        await asyncio.sleep(0)
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", boundary)
    gateway = Gateway()
    result = await run(gateway, timeout=1.0)
    assert result[0] is True
    assert gateway.calls == 1


class ObservableFuture(concurrent.futures.Future):
    def __init__(self) -> None:
        super().__init__()
        self.exception_calls = 0

    def exception(self, timeout: float | None = None):
        self.exception_calls += 1
        return super().exception(timeout)


@pytest.mark.asyncio
async def test_e_pending_timeout_drains_late_source_and_wrapper_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    source = ObservableFuture()

    class ObservableAsyncFuture(asyncio.Future):
        exception_calls = 0

        def exception(self):
            self.exception_calls += 1
            return super().exception()

    wrapped = ObservableAsyncFuture()

    class Gateway:
        def verify(self, command_id: str, kind: str, target: str | None, payload: dict[str, Any]) -> concurrent.futures.Future:
            return source

    def wrap(future: concurrent.futures.Future) -> asyncio.Future:
        def transfer(done: concurrent.futures.Future) -> None:
            error = done.exception()
            if error is not None:
                wrapped.set_exception(error)
            else:
                wrapped.set_result(done.result())

        future.add_done_callback(lambda done: asyncio.get_running_loop().call_soon(transfer, done))
        return wrapped

    async def timeout(awaitable: Any, timeout: float) -> Any:
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wrap_future", wrap)
    monkeypatch.setattr(asyncio, "wait_for", timeout)
    result = await run(Gateway(), timeout=1.0)
    assert result[0] is None
    source.set_exception(RuntimeError("late timeout"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert source.exception_calls >= 2
    assert wrapped.exception_calls == 1


@pytest.mark.asyncio
async def test_f_cancellation_propagates_without_retry_and_production_drains_exception() -> None:
    source = ObservableFuture()
    loop = asyncio.get_running_loop()
    unhandled: list[dict[str, Any]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda current, context: unhandled.append(context))

    class Gateway:
        calls = 0

        def verify(self, *args: Any) -> concurrent.futures.Future:
            self.calls += 1
            return source

    gateway = Gateway()
    try:
        task = asyncio.create_task(run(gateway, timeout=1.0))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        source.set_exception(RuntimeError("late"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert gateway.calls == 1
        assert source.exception_calls >= 2
        assert unhandled == []
    finally:
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_g_exception_ambiguity_retains_lock_and_emits_alert_on_hot_path() -> None:
    gateway = ScriptedGateway([(0.001, RuntimeError(str(index))) for index in range(20)])
    events: list[Any] = []

    class Bus:
        boot_id = "boot"

        async def publish(self, envelope: Any, *, mutates_state: bool) -> None:
            events.append(envelope)

    pipeline = pipeline_for(gateway)
    pipeline._risk_config = SimpleNamespace(verification_timeout_s=0.11, verify_poll_interval_ms=30)
    pipeline._bus = Bus()
    pipeline._runtime_id = "runtime"
    pipeline._locks = {"entry:XAUUSDm"}
    pipeline._pending = SimpleNamespace(retain_for_reconciliation=lambda ticket: None)
    transitions: list[tuple[str, str | None]] = []

    async def transition(record: Any, state: str, *, reason: str | None = None, event_type: str | None = None, extra: Any = None) -> Any:
        transitions.append((state, reason))
        return record

    pipeline._transition_internal = transition
    pipeline._envelope = lambda *args, **kwargs: SimpleNamespace(type=args[1])
    record = SimpleNamespace(command_id="command", correlation_id="correlation")
    await pipeline._unknown_internal(record, "INTERNAL_ENTRY_MARKET", "entry:XAUUSDm", None, "OUTCOME_AMBIGUOUS", {"symbol": "XAUUSDm"})
    assert transitions[-1] == ("FAILED", "OUTCOME_AMBIGUOUS")
    assert "entry:XAUUSDm" in pipeline._locks
    assert any(event.type == "alert.created" for event in events)
