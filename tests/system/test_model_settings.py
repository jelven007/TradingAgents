"""Offline settings persistence, scope, frozen execution and real local HTTP probes."""

import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tradingagents.application import worker
from tradingagents.application.execution import execution_status
from tradingagents.application.model_probe import probe_model
from tradingagents.application.service import ResearchService
from tradingagents.domain.model_settings import (
    ModelProbeInput,
    ModelSettingsInput,
    SettingsConflict,
    TierSettings,
)
from tradingagents.domain.service import SubmitRequest
from tradingagents.infrastructure.identity import SCOPES
from tradingagents.infrastructure.model_settings import ModelSettingsStore
from tradingagents.infrastructure.recovery import backup, restore
from tradingagents.infrastructure.reports import database
from tradingagents.interfaces.api import make_server
from tradingagents.llm_clients.credentials import TIER_OPTIONS, check_destination, model_credentials
from tradingagents.llm_clients.factory import create_tier_client


@pytest.fixture
def service(tmp_path):
    return ResearchService(tmp_path / "store.sqlite", tmp_path / "artifacts", {
        "research": {"daily": {"config": {"research_policy": {"approved_tickers": ["NVDA"]}}}},
    })


def principal(service, subject="author", scopes=SCOPES):
    _, token = service.identities.issue(subject, "research", scopes)
    return service.identities.authenticate(token), token


def request_body():
    return SubmitRequest.model_validate({
        "workspace": "research", "experiment": "settings", "template": "daily",
        "mandate": {
            "ticker": "NVDA", "analysis_date": "2026-01-09",
            "prediction_horizon_trading_days": 5, "benchmark": "SPY",
            "quote_currency": "USD", "valid_until": "2099-01-01",
        },
    })


def draft(version=0, *, quick_key="qa-quick-secret", deep_key="qa-deep-secret", **changes):
    raw = {"expected_version": version}
    for tier, key in (("quick", quick_key), ("deep", deep_key)):
        raw[tier] = {"provider": "deepseek", "model": f"qa-{tier}", "api_key": key,
                     "base_url": "https://api.deepseek.com"}
        raw[tier].update(changes.get(tier, {}))
    return ModelSettingsInput.model_validate(raw)


def test_keys_encrypted_restart_retention_clear_and_destination_change(service):
    author, _ = principal(service)
    assert service.settings(author)["version"] == 0
    service.save_settings(author, draft())
    store = ModelSettingsStore(service.tasks.path)
    public = service.settings(author)
    assert public["version"] == 1 and public["quick"]["api_key_configured"]
    config = store.effective("research", service.templates["research"]["daily"].config)
    assert store.frozen_credentials(config) == {"quick": "qa-quick-secret", "deep": "qa-deep-secret"}
    assert stat.S_IMODE(store.key_path.stat().st_mode) == 0o600
    with database(store.path) as db:
        dump = "\n".join(db.iterdump())
    for key in ("qa-quick-secret", "qa-deep-secret"):
        assert key not in dump and key not in json.dumps(public)
    service.save_settings(author, draft(1, quick_key="", deep_key=""))
    second = store.effective("research", service.templates["research"]["daily"].config)
    assert store.frozen_credentials(second) == store.frozen_credentials(config)
    with pytest.raises(SettingsConflict):
        service.save_settings(author, draft(1))
    service.save_settings(author, draft(
        2, quick_key="", deep_key="", quick={"clear_api_key": True},
        deep={"base_url": "https://relay.example/v1"},
    ))
    assert not service.settings(author)["quick"]["api_key_configured"]
    assert not service.settings(author)["deep"]["api_key_configured"]
    assert store.frozen_credentials(config)["quick"] == "qa-quick-secret"
    assert TIER_OPTIONS.get() == {}


def test_new_task_uses_settings_existing_task_frozen_and_worker_key_context(service, monkeypatch):
    author, _ = principal(service)
    old = service.submit(author, request_body(), "old")["id"]
    service.save_settings(author, draft())
    first = service.submit(author, request_body(), "managed-one")["id"]
    config = service.tasks.get(first)["payload"]["config"]
    assert "model_settings_revision" not in service.tasks.get(old)["payload"]["config"]
    assert execution_status(config, service.tasks.path)["credentials_present"]
    service.save_settings(author, draft(1, quick_key="replacement-quick"))
    second = service.submit(author, request_body(), "managed-two")["id"]
    second_config = service.tasks.get(second)["payload"]["config"]
    assert config["model_settings_revision"] != second_config["model_settings_revision"]
    assert "qa-quick-secret" not in json.dumps(service.tasks.get(first))
    assert service.tasks.get(first)["payload"]["config"] == config
    row = service.tasks.claim("test", task_id=first)
    observed = {}

    def fake_run(root, scope, mandate, incoming, **kwargs):
        observed.update(config=incoming, quick=TIER_OPTIONS.get()["quick"]["api_key"],
                        deep=TIER_OPTIONS.get()["deep"]["api_key"])
        raise RuntimeError("controlled worker exit")

    monkeypatch.setattr(worker, "execute_research", fake_run)
    worker._child(str(service.tasks.path), str(service.root), first, row["attempt"])
    assert observed == {"config": config, "quick": "qa-quick-secret", "deep": "qa-deep-secret"}
    assert TIER_OPTIONS.get() == {} and service.tasks.get(first)["status"] == "failed"


def test_explicit_tier_credentials_override_environment_and_azure_configuration(service, monkeypatch):
    author, _ = principal(service)
    service.save_settings(author, draft())
    config = service.model_settings.effective("research", service.templates["research"]["daily"].config)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "different-env-secret")
    with model_credentials(config, {"quick": "qa-quick-secret", "deep": "qa-deep-secret"}):
        quick = create_tier_client(config, "quick").get_llm()
        deep = create_tier_client(config, "deep").get_llm()
        assert quick.openai_api_key.get_secret_value() == "qa-quick-secret"
        assert deep.openai_api_key.get_secret_value() == "qa-deep-secret"
    assert os.environ["DEEPSEEK_API_KEY"] == "different-env-secret"
    from tradingagents.llm_clients.azure_client import AzureOpenAIClient
    azure = AzureOpenAIClient(
        "test-deployment", api_key="azure-qa", azure_endpoint="https://resource.openai.azure.com",
        azure_deployment="test-deployment", api_version="2025-03-01-preview", max_tokens=64,
    ).get_llm()
    assert azure.deployment_name == "test-deployment" and azure.max_tokens == 64


@pytest.mark.parametrize("endpoint", [
    "http://api.deepseek.com", "https://user:secret@api.deepseek.com",
    "https://api.deepseek.com?key=secret", "https://169.254.169.254",
    "https://10.0.0.1", "https://localhost", "https://host.local",
    "https://api.deepseek.com:444", "http://127.0.0.1:80",
])
def test_invalid_or_private_endpoints_are_rejected(endpoint):
    with pytest.raises(ValueError):
        TierSettings(provider="deepseek", model="test", base_url=endpoint)


def test_dns_private_destination_rejected(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(0, 0, 0, "", ("10.1.2.3", 443))])
    with pytest.raises(ValueError, match="public"):
        check_destination("deepseek", "https://relay.example/v1")


def test_blank_model_is_rejected():
    with pytest.raises(ValueError):
        TierSettings(provider="deepseek", model="   ")


def test_probe_validates_only_selected_tier_and_reuses_saved_key(service, monkeypatch):
    from tradingagents.application import service as service_module
    author, _ = principal(service)
    service.save_settings(author, draft())
    seen = []

    def probe(record, key, tier):
        seen.append((record["model"], key, tier))
        return {"ok": True, "category": "connected", "elapsed_ms": 1}

    monkeypatch.setattr(service_module, "probe_model", probe)
    data = ModelProbeInput(expected_version=1, tier="quick", settings=draft().quick.model_copy(
        update={"api_key": None},
    ))
    assert service.test_settings(author, data)["ok"]
    assert seen == [("qa-quick", "qa-quick-secret", "quick")]
    assert service.settings(author)["version"] == 1
    with pytest.raises(SettingsConflict):
        service.test_settings(author, data.model_copy(update={"expected_version": 0}))


def test_scoped_http_save_conflict_and_error_do_not_echo_key(service, loopback_network):
    _, token = principal(service)
    _, reader_token = principal(service, "reader", scopes={"settings:read"})
    _, ordinary_token = principal(service, "ordinary", scopes={"task:create"})
    server = make_server(service)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))

    def call(token, data=None, path="/settings/models"):
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        req = Request(f"http://127.0.0.1:{server.server_port}{path}", headers=headers,
                      data=json.dumps(data).encode() if data is not None else None)
        try:
            with opener.open(req) as response:
                return response.status, response.read()
        except HTTPError as exc:
            return exc.code, exc.read()

    raw = draft().model_dump(mode="json")
    for tier in ("quick", "deep"):
        raw[tier]["api_key"] = f"qa-{tier}-secret"
    try:
        assert call(ordinary_token)[0] == 403
        assert call(reader_token)[0] == 200
        assert call(reader_token, raw)[0] == 403
        assert call(token, raw)[0] == 200
        assert call(token, raw)[0] == 409
        raw["quick"]["model"] = ""
        status, body = call(token, raw)
        assert status == 400 and b"qa-quick-secret" not in body
        assert call(reader_token, raw, "/settings/models/test")[0] == 403
        assert b"qa-quick-secret" not in call(token)[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_real_local_probe_success_failure_single_call_and_no_persistence(loopback_network, tmp_path):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, self.headers["Authorization"], body))
            fail = body["model"] == "bad-model"
            content = json.dumps(
                {"error": {"message": "qa-secret-not-for-response", "type": "invalid_api_key"}}
                if fail else {
                    "id": "qa", "object": "chat.completion", "created": 1, "model": "local-qa",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
                }
            ).encode()
            redirect = body["model"] == "redirect-model"
            self.send_response(302 if redirect else 401 if fail else 200)
            if body["model"] == "redirect-model":
                self.send_header("Location", "/credential-leak")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    record = {"provider": "openai_compatible", "model": "local-qa",
              "base_url": f"http://127.0.0.1:{server.server_port}/v1", "api_version": ""}
    try:
        result = probe_model(record, "qa-local-secret", "quick")
        assert result["ok"] and result["usage"]["total_tokens"] == 6
        assert len(calls) == 1 and calls[0][1] == "Bearer qa-local-secret"
        assert calls[0][2].get("max_tokens", calls[0][2].get("max_completion_tokens")) == 64
        result = probe_model({**record, "model": "bad-model"}, "qa-local-secret", "deep")
        assert result["category"] == "authentication" and len(calls) == 2
        assert "secret" not in json.dumps(result) and "OK" not in json.dumps(result)
        result = probe_model({**record, "model": "redirect-model"}, "qa-local-secret", "quick")
        assert not result["ok"] and len(calls) == 3
        result = probe_model(record, "qa-local-secret", "quick", deadline=0.01)
        assert result["category"] == "timeout" and len(calls) == 3
        assert not list(tmp_path.iterdir())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_restore_keeps_public_settings_but_requires_new_keys(service, tmp_path):
    author, _ = principal(service)
    service.save_settings(author, draft())
    manifest = backup(service.tasks.path, service.root, tmp_path / "backup")
    recovered_path = restore(tmp_path / "backup", manifest, tmp_path / "restored")
    store = ModelSettingsStore(recovered_path)
    baseline = service.templates["research"]["daily"].config
    assert not store.public("research", baseline)["quick"]["api_key_configured"]
    assert not store.key_path.exists()
    config = store.effective("research", baseline)
    assert not execution_status(config, recovered_path)["credentials_present"]
    store.save("research", draft(1, quick_key="recovered-quick", deep_key="recovered-deep"), "operator")
    assert store.public("research", baseline)["quick"]["api_key_configured"]
