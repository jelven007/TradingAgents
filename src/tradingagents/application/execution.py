"""Bounded local execution requests; only the explicitly requested task is claimed."""

from __future__ import annotations

import os
import threading
from contextlib import suppress

from tradingagents.application.worker import run_one
from tradingagents.infrastructure.model_settings import ModelSettingsStore
from tradingagents.infrastructure.tasks import BudgetExceeded
from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.factory import tier_provider


def execution_status(config: dict, db_path=None) -> dict:
    """Report credential presence only; this does not certify provider connectivity."""
    managed = bool(config.get("model_settings_revision"))
    keys = {}
    if managed and db_path:
        with suppress(ValueError):
            keys = ModelSettingsStore(db_path).frozen_credentials(config)
    missing = []
    for tier in ("quick", "deep"):
        provider = tier_provider(config, tier)
        if provider in {"ollama", "bedrock", "chatgpt"}:
            continue  # These adapters perform their own local/AWS/login checks.
        key = get_api_key_env(provider)
        present = keys.get(tier) if managed else (os.environ.get(key) if key else None)
        if provider == "openai_compatible":
            continue
        if not present or present == "placeholder":
            missing.append(provider)
    return {"credentials_present": not missing, "missing_providers": sorted(set(missing)),
            "provider_connectivity_verified": False}


class LocalExecution:
    def __init__(self, store, root, *, max_concurrency=2):
        self.store, self.root = store, root
        self.max_concurrency = max_concurrency
        self.lock = threading.Lock()
        self.active: set[str] = set()

    def start(self, task_id: str, *, report_actor: str | None = None):
        with self.lock:
            if report_actor is not None:
                self.store.request_report(task_id, report_actor)
            if task_id in self.active:
                return
            if len(self.active) >= self.max_concurrency:
                raise BudgetExceeded("local execution capacity reached")
            self.active.add(task_id)
            try:
                threading.Thread(target=self._run, args=(task_id,), daemon=True).start()
            except BaseException:
                self.active.remove(task_id)
                raise

    def _run(self, task_id: str):
        try:
            run_one(self.store, self.root, "web-worker", max_concurrency=self.max_concurrency,
                    task_id=task_id)
        finally:
            with self.lock:
                self.active.discard(task_id)

    def close(self):
        with self.lock:
            active = list(self.active)
        for task in active:
            with suppress(KeyError):
                self.store.cancel(task, "local-service-shutdown")
