"""Execution-local credentials and HTTP transports, never process-global environment."""

from __future__ import annotations

import ipaddress
import socket
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from urllib.parse import urlsplit

import httpx

from tradingagents.domain.model_settings import TIERS, validate_endpoint

TIER_OPTIONS: ContextVar = ContextVar("managed_model_options", default=MappingProxyType({}))


def check_destination(provider: str, endpoint: str):
    endpoint = validate_endpoint(provider, endpoint)
    host = urlsplit(endpoint).hostname
    if host in {"localhost", "127.0.0.1", "::1"}:
        return
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("model endpoint must resolve to public addresses")


@contextmanager
def model_credentials(config: dict, keys: dict):
    """Keep independent quick/deep keys in this invocation; close owned transports."""
    options, clients = {}, []
    try:
        for tier in TIERS:
            if tier not in keys:
                continue
            provider = config[f"{tier}_think_provider"]
            endpoint = config[f"{tier}_think_backend_url"]
            # Empty is explicit: managed settings must never inherit a different env key.
            value = {"api_key": keys[tier] or ("ollama" if provider == "ollama" else "EMPTY")}
            if provider == "azure":
                value.update(azure_endpoint=endpoint, azure_deployment=config[f"{tier}_think_llm"],
                             api_version=config[f"{tier}_think_api_version"])
            if provider != "google":
                expected = urlsplit(endpoint)

                def guard(request, *, provider=provider, endpoint=endpoint, expected=expected):
                    target = urlsplit(str(request.url))
                    if (target.scheme, target.hostname, target.port) != (
                        expected.scheme, expected.hostname, expected.port,
                    ):
                        raise ValueError("model request left its configured endpoint")
                    check_destination(provider, endpoint)

                async def async_guard(request, *, guard=guard):
                    guard(request)

                sync = httpx.Client(follow_redirects=False, trust_env=False,
                                    event_hooks={"request": [guard]})
                asynchronous = httpx.AsyncClient(follow_redirects=False, trust_env=False,
                                                 event_hooks={"request": [async_guard]})
                clients.append((sync, asynchronous))
                value.update(http_client=sync, http_async_client=asynchronous)
            options[tier] = value
        token = TIER_OPTIONS.set(options)
        try:
            yield
        finally:
            TIER_OPTIONS.reset(token)
    finally:
        for sync, asynchronous in clients:
            sync.close()
            # SDK calls here are synchronous. Close the unused async transports as well.
            import asyncio
            asyncio.run(asynchronous.aclose())
