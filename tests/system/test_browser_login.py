"""Local first-run accounts, cookie authentication, authorization and logout."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

import pytest

from tradingagents.application.service import ResearchService
from tradingagents.infrastructure.browser_accounts import (
    AccountInput,
    BrowserAccounts,
    LoginInput,
    LoginThrottled,
)
from tradingagents.infrastructure.identity import AuthenticationError
from tradingagents.infrastructure.recovery import backup, restore
from tradingagents.infrastructure.reports import database
from tradingagents.interfaces.api import make_server


@pytest.fixture
def service(tmp_path):
    return ResearchService(tmp_path / "db", tmp_path / "artifacts", {
        "research": {"daily": {"config": {"research_policy": {"approved_tickers": ["NVDA"]}}}},
    })


def test_first_account_atomic_password_hash_and_role_fixed(service):
    data = AccountInput(username="ADMIN", password="synthetic-password", role="reviewer")

    def setup(_):
        try:
            return service.accounts.create("research", data, first=True)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(setup, range(4)))
    assert sum(value is not None for value in results) == 1
    assert service.accounts.list("research")[0]["role"] == "admin"
    assert not service.accounts.setup_required()
    with database(service.tasks.path) as db:
        assert "synthetic-password" not in "\n".join(db.iterdump())
    token = service.accounts.login(LoginInput(username="admin", password="synthetic-password"))
    principal, account = service.accounts.authenticate(token)
    assert principal.subject.startswith("user-") and "settings:write" in principal.scopes
    assert account["role"] == "admin"
    service.accounts.logout(token)
    with pytest.raises(AuthenticationError):
        service.accounts.authenticate(token)


def test_password_failure_throttle_and_expiry(service):
    now = [1000]
    accounts = BrowserAccounts(service.tasks.path, clock=lambda: now[0])
    accounts.create("research", AccountInput(username="admin", password="synthetic-password"), first=True)
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            accounts.login(LoginInput(username="admin", password="wrong-password"))
    with pytest.raises(LoginThrottled):
        accounts.login(LoginInput(username="admin", password="synthetic-password"))
    now[0] += 61
    token = accounts.login(LoginInput(username="admin", password="synthetic-password"))
    now[0] += 8 * 86400
    with pytest.raises(AuthenticationError):
        accounts.authenticate(token)
    with pytest.raises(ValueError):
        AccountInput(username="reviewer", password="short")


def test_home_setup_cookie_pages_refresh_accounts_csrf_logout(service, loopback_network):
    server = make_server(service, browser_accounts=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    jar = CookieJar()
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar))

    def call(path, data=None, csrf=None, headers=None, client=opener):
        sent = {"Content-Type": "application/json", "X-Workbench-Client": "web"}
        if csrf:
            sent["X-Workbench-CSRF"] = csrf
        sent.update(headers or {})
        req = Request(f"http://127.0.0.1:{server.server_port}{path}", headers=sent,
                      data=json.dumps(data).encode() if data is not None else None)
        try:
            with client.open(req, timeout=5) as response:
                return response.status, dict(response.headers), json.loads(response.read())
        except HTTPError as error:
            return error.code, dict(error.headers), json.loads(error.read())

    try:
        assert call("/auth/status")[2]["data"]["setup_required"]
        assert call("/auth/session")[0] == 401
        body = {"username": "admin", "password": "synthetic-password"}
        assert call("/auth/setup", body, headers={"Origin": "https://untrusted.example"})[0] == 403
        assert call("/auth/setup", body, headers={"X-Workbench-Client": ""})[0] == 403
        status, headers, result = call("/auth/setup", body)
        assert status == 200
        assert "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
        identity = result["data"]
        csrf = identity["csrf"]
        assert identity["account"]["username"] == "admin"
        assert "accounts:manage" in identity["scopes"]
        assert call("/auth/setup", {"username": "attacker", "password": "test-password"})[0] == 400
        for path in ("/session", "/tasks", "/reports", "/experiments", "/operations", "/audit",
                     "/settings/models", "/accounts"):
            assert call(path)[0] == 200, path
        account = {"username": "reviewer", "password": "reviewer-password", "role": "reviewer"}
        assert call("/accounts", account)[0] == 403
        assert call("/accounts", account, csrf="invalid")[0] == 403
        assert call("/accounts", account, csrf=csrf)[0] == 200
        assert "reviewer-password" not in json.dumps(call("/accounts")[2])
        _, bearer = service.identities.issue("limited", "research", {"task:read"})
        assert call("/accounts", headers={"Authorization": "Bearer " + bearer})[0] == 403
        assert call("/auth/logout", {}, csrf=csrf)[0] == 200
        assert not list(jar)
        assert call("/tasks")[0] == 401
        assert call("/auth/login", {"username": "admin", "password": "wrong"})[0] == 401
        result = call("/auth/login", account | {"role": None})  # Unknown fields rejected.
        assert result[0] == 400
        result = call("/auth/login", {"username": "reviewer", "password": "reviewer-password"})[2]["data"]
        assert "settings:write" not in result["scopes"]
        assert call("/accounts")[0] == 403
        assert call("/operations")[0] == 403
        assert call("/settings/models")[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_browser_account_entry_is_not_enabled_in_bearer_service(service, loopback_network):
    server = make_server(service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{server.server_port}/auth/status") as response:
            assert not json.loads(response.read())["data"]["accounts_enabled"]
        req = Request(f"http://127.0.0.1:{server.server_port}/auth/setup",
                      data=b'{"username":"admin","password":"test-password"}')
        with pytest.raises(HTTPError) as error:
            opener.open(req)
        assert error.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_restore_revokes_browser_session_but_keeps_password_account(service, tmp_path):
    service.accounts.create("research", AccountInput(username="admin", password="test-password"), first=True)
    token = service.accounts.login(LoginInput(username="admin", password="test-password"))
    manifest = backup(service.tasks.path, service.root, tmp_path / "backup")
    recovered = restore(tmp_path / "backup", manifest, tmp_path / "restored")
    accounts = BrowserAccounts(recovered)
    with pytest.raises(AuthenticationError):
        accounts.authenticate(token)
    assert not accounts.setup_required()
    new_token = accounts.login(LoginInput(username="admin", password="test-password"))
    assert accounts.authenticate(new_token)[1]["username"] == "admin"
