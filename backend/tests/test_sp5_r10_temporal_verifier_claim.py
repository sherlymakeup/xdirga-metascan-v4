from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import threading
from typing import Any

import pytest

from metascan.pipeline.command_pipeline import CommandPipeline


class ObservableFuture(concurrent.futures.Future):
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
    def __init__(self, source: ObservableFuture) -> None:
        self.source = source
        self.submissions = 0
        self.active = 0
        self.max_concurrency = 0

    def verify(self, *args: Any) -> ObservableFuture:
        self.submissions += 1
        self.active += 1
        self.max_concurrency = max(self.max_concurrency, self.active)
        self.source.add_done_callback(lambda _: setattr(self, "active", self.active - 1))
        return self.source


def pipeline_for(gateway: Gateway) -> CommandPipeline:
    pipeline = CommandPipeline.__new__(CommandPipeline)
    pipeline._gateway = gateway
    return pipeline


async def verify(gateway: Gateway):
    return await pipeline_for(gateway)._temporal_verify(
        "command", "INTERNAL_ENTRY_MARKET", None, {}, timeout=1.0, poll_interval_ms=30
    )


async def wait_thread(event: threading.Event) -> None:
    while not event.is_set():
        await asyncio.sleep(0)


def controlled_source() -> tuple[ObservableFuture, threading.Event, threading.Event, threading.Event]:
    source = ObservableFuture()
    prior_entered = threading.Event()
    release_prior = threading.Event()
    verifier_started = threading.Event()

    def prior(_: concurrent.futures.Future) -> None:
        prior_entered.set()
        assert release_prior.wait(2)

    source.add_done_callback(prior)
    original_add_done_callback = source.add_done_callback
    registrations = 0

    def add_done_callback(callback: Any) -> None:
        nonlocal registrations
        registrations += 1
        if registrations == 2:
            def observed(future: concurrent.futures.Future) -> None:
                verifier_started.set()
                callback(future)
            original_add_done_callback(observed)
        else:
            original_add_done_callback(callback)

    source.add_done_callback = add_done_callback  # type: ignore[method-assign]
    return source, prior_entered, release_prior, verifier_started


def start_completion(source: ObservableFuture, completion: Any) -> threading.Thread:
    def complete() -> None:
        if completion == "cancel":
            source.cancel()
        elif isinstance(completion, Exception):
            source.set_exception(completion)
        else:
            source.set_result(completion)

    worker = threading.Thread(target=complete)
    worker.start()
    return worker


def assert_accounting(gateway: Gateway, source: ObservableFuture, *, results: int) -> None:
    assert gateway.submissions == 1
    assert gateway.max_concurrency == 1
    assert source.exception_calls == 1
    assert source.result_calls == results


@pytest.mark.asyncio
async def test_a_timeout_claims_finished_success_before_blocked_callback_release(monkeypatch: pytest.MonkeyPatch) -> None:
    source, prior_entered, release_prior, verifier_started = controlled_source()
    gateway = Gateway(source)
    worker: threading.Thread | None = None

    async def timeout_after_finished(awaitable: Any, timeout: float) -> Any:
        nonlocal worker
        worker = start_completion(source, {"positionExists": True})
        await wait_thread(prior_entered)
        assert source.done()
        assert not verifier_started.is_set()
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", timeout_after_finished)
    result = await verify(gateway)
    assert result[0] is True
    assert not verifier_started.is_set()
    assert_accounting(gateway, source, results=1)
    release_prior.set()
    assert worker is not None
    worker.join(2)


@pytest.mark.asyncio
async def test_b_timeout_claims_finished_ordinary_exception_once(monkeypatch: pytest.MonkeyPatch) -> None:
    source, prior_entered, release_prior, verifier_started = controlled_source()
    gateway = Gateway(source)
    worker: threading.Thread | None = None

    async def timeout_after_finished(awaitable: Any, timeout: float) -> Any:
        nonlocal worker
        worker = start_completion(source, RuntimeError("ambiguous"))
        await wait_thread(prior_entered)
        assert source.done()
        assert not verifier_started.is_set()
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", timeout_after_finished)
    result = await verify(gateway)
    assert result[0] is None
    assert_accounting(gateway, source, results=0)
    release_prior.set()
    assert worker is not None
    worker.join(2)


@pytest.mark.asyncio
async def test_c_task_cancellation_leaves_finished_source_for_callback_cleanup() -> None:
    source, prior_entered, release_prior, verifier_started = controlled_source()
    gateway = Gateway(source)
    contexts: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda current, context: contexts.append(context))
    task = asyncio.create_task(verify(gateway))
    while gateway.submissions == 0:
        await asyncio.sleep(0)
    worker = start_completion(source, "cancel")
    await wait_thread(prior_entered)
    assert source.done()
    assert not verifier_started.is_set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release_prior.set()
    worker.join(2)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    loop.set_exception_handler(previous)
    assert verifier_started.is_set()
    assert_accounting(gateway, source, results=0)
    assert contexts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", ["callback", "timeout"])
async def test_d_claim_and_publication_are_atomic_for_both_ownership_winners(
    monkeypatch: pytest.MonkeyPatch, winner: str
) -> None:
    source, prior_entered, release_prior, verifier_started = controlled_source()
    gateway = Gateway(source)
    loop = asyncio.get_running_loop()
    original_notify = loop.call_soon_threadsafe
    notifications = 0

    def counted_notify(callback: Any, *args: Any, **kwargs: Any) -> None:
        nonlocal notifications
        notifications += 1
        original_notify(callback, *args, **kwargs)

    monkeypatch.setattr(loop, "call_soon_threadsafe", counted_notify)
    worker: threading.Thread | None = None

    async def boundary(awaitable: Any, timeout: float) -> Any:
        nonlocal worker
        worker = start_completion(source, {"positionExists": True})
        await wait_thread(prior_entered)
        assert source.done()
        assert not verifier_started.is_set()
        if winner == "callback":
            release_prior.set()
            await wait_thread(verifier_started)
            return await awaitable
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", boundary)
    result = await verify(gateway)
    assert result[0] is True
    assert_accounting(gateway, source, results=1)
    if winner == "timeout":
        assert notifications == 0
        release_prior.set()
        await wait_thread(verifier_started)
        await asyncio.sleep(0)
        assert notifications == 0
        assert_accounting(gateway, source, results=1)
    else:
        assert notifications == 1
    assert worker is not None
    worker.join(2)


def test_e_claim_is_published_before_ownership_becomes_visible() -> None:
    source = inspect.getsource(CommandPipeline._temporal_verify)
    claim = source[source.index("        def claim("):source.index("        def complete(")]
    assert claim.index("handoff.append((result, error))") < claim.index("claimed = True")
    assert "BaseException" not in claim
