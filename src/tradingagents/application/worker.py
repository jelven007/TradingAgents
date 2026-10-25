"""Bounded local worker: one spawned graph process per fenced attempt."""

from __future__ import annotations

import multiprocessing
import os
import threading
from contextlib import suppress
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler

from tradingagents.application.runs import RunScope, execute_research
from tradingagents.domain.tasks import TaskInput
from tradingagents.infrastructure.model_settings import ModelSettingsStore
from tradingagents.infrastructure.reports import ReportStore
from tradingagents.infrastructure.tasks import LeaseLost, TaskStore
from tradingagents.llm_clients.credentials import model_credentials


class BudgetCallback(BaseCallbackHandler):
    raise_error = True
    run_inline = True

    def __init__(self, store: TaskStore, task_id: str, attempt: str):
        self.store, self.task_id, self.attempt = store, task_id, attempt

    def on_chain_start(self, serialized, inputs, *, run_id, **kwargs):
        stage = (kwargs.get("metadata") or {}).get("langgraph_node")
        self.store.progress(self.task_id, self.attempt, stage)

    def _start(self, serialized, run_id, kwargs):
        params = kwargs.get("invocation_params") or {}
        model = params.get("model") or params.get("model_name") or (serialized or {}).get("name")
        self.store.reserve_call(self.task_id, self.attempt, str(run_id), str(model or "unknown"))

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._start(serialized, run_id, kwargs)

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self._start(serialized, run_id, kwargs)

    def on_llm_end(self, response, *, run_id, **kwargs):
        usage = None
        if response.generations and response.generations[0]:
            message = getattr(response.generations[0][0], "message", None)
            usage = getattr(message, "usage_metadata", None)
        if not usage:
            tokens = (response.llm_output or {}).get("token_usage", {})
            usage = {"input_tokens": tokens.get("prompt_tokens"),
                     "output_tokens": tokens.get("completion_tokens"),
                     "total_tokens": tokens.get("total_tokens")}
        self.store.finish_call(str(run_id), usage=usage)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self.store.finish_call(str(run_id), failed=True)


def _child(db_path: str, root: str, task_id: str, attempt: str):
    store = TaskStore(Path(db_path))
    stop = threading.Event()

    def watchdog():
        # A dead parent must not leave an unbounded, billable graph process.
        while not stop.wait(0.5):
            try:
                store.check_lease(task_id, attempt)
            except Exception:
                os._exit(75)

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        row = store.get(task_id)
        store.check_lease(task_id, attempt)
        payload = TaskInput.model_validate(row["payload"])
        keys = ModelSettingsStore(Path(db_path)).frozen_credentials(payload.config)
        with model_credentials(payload.config, keys):
            result = execute_research(
                Path(root), RunScope(payload.workspace, payload.experiment, task_id, attempt),
                payload.mandate, payload.config, selected_analysts=payload.selected_analysts,
                portfolio=payload.portfolio, allocation=payload.allocation,
                allocation_valuation=payload.allocation_valuation,
                callbacks=[BudgetCallback(store, task_id, attempt)],
                expected_implementation=row["implementation"],
            )
        store.complete(task_id, attempt, result.path, result.manifest_sha256)
    except Exception as exc:
        with suppress(LeaseLost):
            store.fail(task_id, attempt, type(exc).__name__)
    finally:
        stop.set()


def finalize_report(store: TaskStore, root: Path, task_id: str):
    row = store.get(task_id)
    if row["status"] != "succeeded" or not any(
        e["action"] == "auto_report_requested" for e in row["events"]
    ):
        return
    path = Path(row["result_path"]).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("result path is outside the artifact root")
    report_id = ReportStore(store.path).register(path, row["manifest_hash"], row["author"])
    store.report_registered(task_id, report_id)


def run_one(store: TaskStore, root: Path, worker: str, *, lease_seconds=30,
            max_concurrency=2, poll_seconds=0.25, process_target=None,
            task_id: str | None = None) -> str | None:
    """Claim one task and wait bounded by its deadline; no in-process graph reuse."""
    if not 0 < poll_seconds < lease_seconds / 2:
        raise ValueError("poll interval must be positive and below half the lease")
    row = store.claim(worker, lease_seconds=lease_seconds, max_concurrency=max_concurrency,
                      task_id=task_id)
    if row is None:
        return None
    task_id, attempt = row["id"], row["attempt"]
    child = multiprocessing.get_context("spawn").Process(
        target=process_target or _child,
        args=(str(store.path.resolve()), str(Path(root).resolve()), task_id, attempt),
    )
    try:
        child.start()
        while child.is_alive():
            child.join(timeout=poll_seconds)
            current = store.get(task_id)
            if current["status"] != "running" or current["attempt"] != attempt:
                break
            try:
                store.heartbeat(task_id, attempt, lease_seconds=lease_seconds)
            except LeaseLost:
                break
    finally:
        if child.pid is not None:
            if child.is_alive():
                child.terminate()
            child.join(timeout=2)
            if child.is_alive():
                child.kill()
                child.join(timeout=2)
        current = store.get(task_id)
        if current["status"] == "running" and current["attempt"] == attempt:
            try:
                store.fail(task_id, attempt, "WorkerExited")
            except LeaseLost:
                # Reaping a deadline/expired lease never claims another task.
                store.reap()
    finalize_report(store, root, task_id)
    return task_id
