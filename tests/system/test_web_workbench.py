"""Same-origin workbench assets, scoped listings and explicit local execution."""

import json
import threading
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tradingagents.application.service import ResearchService
from tradingagents.domain.service import SubmitRequest
from tradingagents.infrastructure.identity import SCOPES
from tradingagents.interfaces.api import make_server


@pytest.fixture
def service(tmp_path):
    return ResearchService(tmp_path / "store.sqlite", tmp_path / "artifacts", {
        "research": {"daily": {"config": {
            "research_policy": {"approved_tickers": ["NVDA"]}, "private_setting": "hidden-secret",
        }}},
    })


def request_body(experiment="web"):
    return SubmitRequest.model_validate({
        "workspace": "research", "experiment": experiment, "template": "daily",
        "mandate": {
            "ticker": "NVDA", "analysis_date": "2026-01-09",
            "prediction_horizon_trading_days": 5, "benchmark": "SPY",
            "quote_currency": "USD", "valid_until": "2099-01-01",
        },
    })


def principal(service, subject="author", workspace="research", scopes=SCOPES):
    _, token = service.identities.issue(subject, workspace, scopes)
    return service.identities.authenticate(token), token


def test_session_lists_hide_configuration_and_keep_pagination_scoped(service):
    author, _ = principal(service)
    outsider, _ = principal(service, "outside", "other")
    reader, _ = principal(service, "reader", scopes={"task:read"})
    session = service.session(author)
    assert session["templates"][0]["tickers"] == ["NVDA"]
    assert session["templates"][0]["execution"]["credentials_present"] is False
    assert service.session(reader)["templates"] == []
    for index in range(3):
        service.submit(author, request_body(), f"page-{index}")
    page = service.list_tasks(author, limit=2)
    next_page = service.list_tasks(author, limit=2, offset=2)
    assert page["total"] == next_page["total"] == 3
    assert len(page["items"]) == 2 and len(next_page["items"]) == 1
    assert not ({r["id"] for r in page["items"]} & {r["id"] for r in next_page["items"]})
    assert service.list_tasks(outsider)["items"] == []
    assert "hidden-secret" not in json.dumps([session, page, service.list_reports(author)])
    assert "result_path" not in json.dumps(page)
    with pytest.raises(PermissionError):
        service.list_reports(reader)
    with pytest.raises(PermissionError):
        service.list_experiments(reader)
    for limit, offset in ((0, 0), (101, 0), (50, -1)):
        with pytest.raises(ValueError):
            service.list_tasks(author, limit=limit, offset=offset)


def test_explicit_execution_scope_credentials_and_targeted_claim(service, monkeypatch):
    author, _ = principal(service)
    reader, _ = principal(service, "reader", scopes={"task:read"})
    first = service.submit(author, request_body(), "first")["id"]
    selected = service.submit(author, request_body(), "selected")["id"]
    with pytest.raises(PermissionError):
        service.execute(reader, selected)
    with pytest.raises(ValueError, match="credentials"):
        service.execute(author, selected)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-local-test-key")
    requests = []
    monkeypatch.setattr(service.execution, "start", lambda task_id, **kwargs: requests.append(task_id))
    assert service.execute(author, selected)["execution_requested"] is True
    assert requests == [selected]
    claimed = service.tasks.claim("web", task_id=selected)
    assert claimed["id"] == selected and service.tasks.get(first)["status"] == "queued"
    assert service.tasks.claim("other", task_id=selected) is None
    service.cancel(author, selected)
    with pytest.raises(ValueError, match="queued or running"):
        service.execute(author, selected)


def test_local_execution_starts_only_one_background_run_and_fences_on_close(service, monkeypatch):
    from tradingagents.application import execution
    from tradingagents.infrastructure.tasks import BudgetExceeded

    author, _ = principal(service)
    task = service.submit(author, request_body(), "run")["id"]
    other = service.submit(author, request_body(), "other")["id"]
    began, release = threading.Event(), threading.Event()
    claimed = []

    def run(store, root, worker, *, max_concurrency, task_id):
        claimed.append(store.claim(worker, task_id=task_id)["id"])
        began.set()
        release.wait(5)

    monkeypatch.setattr(execution, "run_one", run)
    service.execution.max_concurrency = 1
    service.execution.start(task)
    assert began.wait(5)
    service.execution.start(task)
    with pytest.raises(BudgetExceeded):
        service.execution.start(other)
    service.execution.close()
    release.set()
    assert claimed == [task]
    assert service.tasks.get(task)["status"] == "cancelled"
    assert service.tasks.get(other)["status"] == "queued"


def test_web_static_and_http_lists_origin_host_and_no_privileged_override(service, loopback_network):
    author, token = principal(service)
    server = make_server(service)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))

    def call(path, *, authenticated=True, body=None, headers=None):
        request_headers = {"Authorization": "Bearer " + token} if authenticated else {}
        request_headers.update(headers or {})
        req = Request(f"http://127.0.0.1:{server.server_port}{path}", headers=request_headers,
                      data=json.dumps(body).encode() if body is not None else None)
        try:
            with opener.open(req, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except HTTPError as error:
            return error.code, dict(error.headers), error.read()

    try:
        status, headers, html = call("/", authenticated=False)
        assert status == 200 and b'TradingAgents' in html and b'/web/app.js' in html
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert "text/html" in headers["Content-Type"]
        for asset in ("app.js", "style.css"):
            assert call("/web/" + asset, authenticated=False)[0] == 200
        assert call("/web/../../.env", authenticated=False)[0] in {400, 404}
        assert call("/session", authenticated=False)[0] == 401
        assert call("/tasks", headers={"Origin": "https://untrusted.example"})[0] == 403
        assert call("/tasks", headers={"Host": "untrusted.example"})[0] == 403
        assert call("/session")[0] == 200
        assert json.loads(call("/tasks?limit=1&offset=0")[2])["data"]["items"] == []
        assert call("/tasks?limit=500")[0] == 400
        assert call("/reports")[0] == call("/experiments")[0] == 200
        task = service.submit(author, request_body(), "http")["id"]
        assert call(f"/tasks/{task}/execute", body={"config": {}})[0] == 400
        assert call(f"/tasks/{task}/execute", body={})[0] == 400
        assert service.tasks.get(task)["status"] == "queued"
        assert call(f"/tasks/{task}/cancel", body={})[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
