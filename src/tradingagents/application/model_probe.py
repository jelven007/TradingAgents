"""One explicit, short model invocation in a process with a hard deadline."""

from __future__ import annotations

import multiprocessing
import time

from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.credentials import check_destination, model_credentials
from tradingagents.llm_clients.factory import create_tier_client


def _probe_child(connection, record, key, tier):
    started = time.monotonic()
    result = {"ok": False, "category": "connection"}
    try:
        check_destination(record["provider"], record["base_url"])
        config = {
            "llm_provider": record["provider"], f"{tier}_think_provider": record["provider"],
            f"{tier}_think_llm": record["model"], f"{tier}_think_backend_url": record["base_url"],
            f"{tier}_think_api_version": record["api_version"],
            "llm_max_retries": 0, "max_tokens": 64,
        }
        with model_credentials(config, {tier: key}):
            llm = create_tier_client(config, tier, timeout=8).get_llm()
            response = llm.invoke("Reply with OK.")
        usage = getattr(response, "usage_metadata", None) or {}
        result = {"ok": True, "category": "connected",
                  "usage": {name: value for name, value in usage.items()
                            if name in {"input_tokens", "output_tokens", "total_tokens"}
                            and isinstance(value, int) and not isinstance(value, bool)}}
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        category = ("authentication" if status in {401, 403} else
                    "rate_limit" if status == 429 else
                    "model_or_request" if status in {400, 404, 422} else
                    "endpoint" if isinstance(exc, ValueError) else
                    "timeout" if "timeout" in type(exc).__name__.lower() else "connection")
        result = {"ok": False, "category": category}
    finally:
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        connection.send(result)
        connection.close()


def probe_model(record: dict, key: str | None, tier: str, *, deadline=15) -> dict:
    if get_api_key_env(record["provider"]) and not key and record["provider"] != "openai_compatible":
        return {"ok": False, "category": "missing_key", "elapsed_ms": 0}
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_probe_child, args=(send, record, key, tier), daemon=True)
    started = time.monotonic()
    try:
        process.start()
        send.close()
        if receive.poll(deadline):
            try:
                return receive.recv()
            except EOFError:
                return {"ok": False, "category": "connection",
                        "elapsed_ms": round((time.monotonic() - started) * 1000)}
        return {"ok": False, "category": "timeout",
                "elapsed_ms": round((time.monotonic() - started) * 1000)}
    finally:
        send.close()
        receive.close()
        if process.pid:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
