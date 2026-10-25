"""Bounded JSON HTTP control plane, intentionally bound to IPv4 loopback."""

from __future__ import annotations

import json
import secrets
import threading
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tradingagents.application.investor import WatchlistInput
from tradingagents.application.service import ResearchService
from tradingagents.domain.evaluation import ExperimentPlan, ObservationInput
from tradingagents.domain.model_settings import (
    ModelProbeInput,
    ModelSettingsInput,
    SettingsConflict,
)
from tradingagents.domain.research_settings import InputError, ResearchSettingsInput
from tradingagents.domain.service import CostRequest, ReviewRequest, SubmitRequest
from tradingagents.infrastructure.artifacts import json_bytes
from tradingagents.infrastructure.browser_accounts import (
    SESSION_SECONDS,
    AccountInput,
    LoginInput,
    LoginThrottled,
)
from tradingagents.infrastructure.identity import AUDIT_REQUEST, AuthenticationError
from tradingagents.infrastructure.tasks import BudgetExceeded


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supersedes: str | None = None


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    enabled: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=4000)


class PredictionRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    report_id: str


def make_server(service: ResearchService, *, port=0, browser_accounts=False) -> ThreadingHTTPServer:
    # Browser account setup is enabled explicitly by the local CLI, for one workspace.
    account_workspace = next(iter(service.templates)) if len(service.templates) == 1 else None
    accounts_enabled = browser_accounts and account_workspace is not None
    live_service = service
    if accounts_enabled:
        from tradingagents.application.demo import DemoSessions
        demos = DemoSessions(service.root.parent / (service.tasks.path.name + ".demos"))
    else:
        demos = None

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(5)
            super().setup()

        def log_message(self, format, *args):
            pass  # Audit is structured; never log bearer headers or request bodies.

        def _content(self, status, content, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
                             "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            if getattr(self, "session_cookie", None):
                self.send_header("Set-Cookie", self.session_cookie)
            self.end_headers()
            self.wfile.write(content)

        def _send(self, status, value):
            self._content(status, json_bytes(value), "application/json; charset=utf-8")

        def _static(self, path):
            if self.command != "GET" or not (path == "/" or path.startswith("/web/")):
                return False
            name = "index.html" if path == "/" else path.removeprefix("/web/")
            if name not in {"index.html", "app.js", "style.css"}:
                raise KeyError("static asset")
            resource = files("tradingagents").joinpath("web", name)
            if not resource.is_file():
                raise KeyError("web bundle not built")
            mime = {"html": "text/html", "js": "text/javascript", "css": "text/css"}
            self._content(200, resource.read_bytes(), mime[name.rsplit(".", 1)[1]] + "; charset=utf-8")
            return True

        def _body(self):
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("chunked bodies are unsupported")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 65536:
                raise ValueError("request body exceeds the limit")
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise ValueError("JSON object required")
            return value

        def _cookie_token(self, kind="session"):
            cookie = SimpleCookie()
            cookie.load(self.headers.get("Cookie", ""))
            value = cookie.get(f"ta_{kind}_{self.server.server_port}")
            return value.value if value else ""

        def _set_cookie(self, token, kind="session"):
            self.session_cookie = (
                f"ta_{kind}_{self.server.server_port}={token}; Path=/; HttpOnly; "
                f"SameSite=Strict; Max-Age={SESSION_SECONDS if token else 0}"
            )

        def _browser_session(self, token):
            principal, account = service.accounts.authenticate(token)
            return principal, {**service.session(principal), "account": {
                "username": account["username"], "role": account["role"],
            }, "csrf": account["csrf"], "auth_method": "password"}

        def _login_request(self):
            if (self.headers.get("X-Workbench-Client") != "web"
                    or self.headers.get_content_type() != "application/json"):
                raise PermissionError("browser login requires a same-origin JSON request")

        def _request(self):
            request_id = uuid.uuid4().hex
            audit_token = AUDIT_REQUEST.set(request_id)
            principal = None
            service = live_service
            try:
                url = urlsplit(self.path)
                host = self.headers.get("Host", "")
                if host not in {f"127.0.0.1:{self.server.server_port}",
                                f"localhost:{self.server.server_port}"}:
                    raise PermissionError("host is outside the local service")
                origin = self.headers.get("Origin")
                if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}",
                                            f"http://localhost:{self.server.server_port}"}:
                    raise PermissionError("cross-origin requests are not allowed")
                if self._static(url.path):
                    return
                parts = url.path.strip("/").split("/")
                if self.command == "GET" and parts == ["auth", "status"]:
                    self._send(200, {"request_id": request_id, "data": {
                        "accounts_enabled": accounts_enabled,
                        "setup_required": accounts_enabled and service.accounts.setup_required(),
                        "workspace": account_workspace if accounts_enabled else None,
                        "demo_enabled": demos is not None,
                    }})
                    return
                if accounts_enabled and parts in (["auth", "setup"], ["auth", "login"]):
                    if self.command != "POST":
                        raise KeyError("route")
                    self._login_request()
                    if not self.server.login_slots.acquire(blocking=False):
                        raise LoginThrottled("login capacity reached")
                    try:
                        if parts[1] == "setup":
                            data = AccountInput.model_validate(self._body())
                            service.accounts.create(account_workspace, data, first=True)
                        else:
                            data = LoginInput.model_validate(self._body())
                        token = service.accounts.login(LoginInput(
                            username=data.username, password=data.password,
                        ))
                        principal, result = self._browser_session(token)
                        self._set_cookie(token)
                        service.identities.audit(principal, "browser:login")
                        self._send(200, {"request_id": request_id, "data": result})
                    finally:
                        self.server.login_slots.release()
                    return
                demo_route = parts[0] == "demo" and demos is not None
                if demo_route and parts == ["demo", "enter"] and self.command == "POST":
                    self._login_request()
                    if self._body():
                        raise ValueError("demo entry body must be empty")
                    token = self._cookie_token("demo")
                    try:
                        service, principal, account = demos.authenticate(token)
                    except AuthenticationError:
                        token = demos.create()
                        service, principal, account = demos.authenticate(token)
                    self._set_cookie(token, "demo")
                    result = {**service.session(principal), "account": account,
                              "csrf": account["csrf"], "auth_method": "demo"}
                    self._send(200, {"request_id": request_id, "data": result})
                    return
                scheme, _, token = self.headers.get("Authorization", "").partition(" ")
                account = None
                if demo_route:
                    token = self._cookie_token("demo")
                    service, principal, account = demos.authenticate(token)
                    parts = parts[1:]
                    if self.command != "GET" and not secrets.compare_digest(
                        self.headers.get("X-Workbench-CSRF", ""), account["csrf"],
                    ):
                        raise PermissionError("demo mutation requires its session CSRF token")
                elif scheme.lower() == "bearer":
                    principal = service.identities.authenticate(token)
                elif accounts_enabled and not scheme:
                    token = self._cookie_token()
                    principal, account = service.accounts.authenticate(token)
                    if self.command != "GET" and not secrets.compare_digest(
                        self.headers.get("X-Workbench-CSRF", ""), account["csrf"],
                    ):
                        raise PermissionError("browser mutation requires its session CSRF token")
                else:
                    raise AuthenticationError("bearer credential required")
                query = parse_qs(url.query)
                pagination = {"limit": int(query.get("limit", ["50"])[0]),
                              "offset": int(query.get("offset", ["0"])[0])}
                result = None
                if self.command == "GET" and parts in (["session"], ["auth", "session"]):
                    result = service.session(principal)
                    if account is not None:
                        result.update(account={"username": account["username"], "role": account["role"]},
                                      csrf=account["csrf"], auth_method="demo" if demo_route else "password")
                elif demo_route and self.command == "POST" and parts == ["role"]:
                    body = self._body()
                    if set(body) != {"role"}:
                        raise ValueError("demo role required")
                    demos.switch(token, body["role"])
                    service, principal, account = demos.authenticate(token)
                    result = {**service.session(principal), "account": account,
                              "csrf": account["csrf"], "auth_method": "demo"}
                elif demo_route and self.command == "POST" and parts == ["auth", "logout"]:
                    if self._body():
                        raise ValueError("logout body must be empty")
                    demos.logout(token)
                    self._set_cookie("", "demo")
                    result = {"logged_out": True}
                elif self.command == "POST" and parts == ["auth", "logout"] and account:
                    if self._body():
                        raise ValueError("logout body must be empty")
                    service.accounts.logout(token)
                    self._set_cookie("")
                    result = {"logged_out": True}
                elif accounts_enabled and self.command == "GET" and parts == ["accounts"]:
                    result = service.list_accounts(principal)
                elif accounts_enabled and self.command == "POST" and parts == ["accounts"]:
                    service.authorize(principal, principal.workspace, "accounts:manage")
                    result = service.create_account(principal, AccountInput.model_validate(self._body()))
                elif self.command == "GET" and parts == ["settings", "models"]:
                    result = service.settings(principal)
                elif self.command == "GET" and parts == ["settings", "research"]:
                    result = service.research_profiles(principal)
                elif self.command == "POST" and parts == ["settings", "research"]:
                    service.authorize(principal, principal.workspace, "settings:write")
                    result = service.save_research_profile(
                        principal, ResearchSettingsInput.model_validate(self._body()),
                    )
                elif self.command == "POST" and parts == ["settings", "models"]:
                    service.authorize(principal, principal.workspace, "settings:write")
                    result = service.save_settings(
                        principal, ModelSettingsInput.model_validate(self._body()),
                    )
                elif self.command == "POST" and parts == ["settings", "models", "test"]:
                    service.authorize(principal, principal.workspace, "settings:write")
                    result = service.test_settings(
                        principal, ModelProbeInput.model_validate(self._body()),
                    )
                elif self.command == "GET" and parts == ["tasks"]:
                    result = service.list_tasks(principal, **pagination)
                elif self.command == "GET" and parts == ["instruments"]:
                    result = service.instruments(
                        principal, query=query.get("q", [""])[0],
                        market=query.get("market", [""])[0], **pagination,
                    )
                elif self.command == "GET" and parts == ["watchlist"]:
                    result = service.investor_home(principal)
                elif self.command == "POST" and parts == ["watchlist"]:
                    service.authorize(principal, principal.workspace, "task:create")
                    result = service.change_watchlist(
                        principal, WatchlistInput.model_validate(self._body()),
                    )
                elif self.command == "GET" and parts == ["reports"]:
                    result = service.list_reports(principal, **pagination)
                elif self.command == "GET" and parts == ["experiments"]:
                    result = service.list_experiments(principal, **pagination)
                elif self.command == "POST" and parts == ["tasks"]:
                    result = service.submit(
                        principal, SubmitRequest.model_validate(self._body()),
                        self.headers.get("Idempotency-Key", ""),
                    )
                elif self.command == "POST" and parts == ["research"]:
                    result = service.research(
                        principal, SubmitRequest.model_validate(self._body()),
                        self.headers.get("Idempotency-Key", ""),
                    )
                elif len(parts) == 2 and parts[0] == "tasks" and self.command == "GET":
                    result = service.task(principal, parts[1])
                elif len(parts) == 3 and parts[0] == "tasks" and self.command == "POST":
                    if parts[2] == "cancel":
                        Registration.model_validate(self._body())
                        result = service.cancel(principal, parts[1])
                    elif parts[2] == "execute":
                        if self._body():
                            raise ValueError("execution request must not override task inputs")
                        result = service.execute(principal, parts[1])
                    elif parts[2] == "report":
                        request = Registration.model_validate(self._body())
                        result = service.register(principal, parts[1], supersedes=request.supersedes)
                elif len(parts) == 2 and parts[0] == "reports" and self.command == "GET":
                    result = service.report(principal, parts[1])
                elif len(parts) == 3 and parts[0] == "reports" and parts[2] == "review":
                    if self.command == "POST":
                        result = service.review(principal, parts[1],
                                                ReviewRequest.model_validate(self._body()))
                elif self.command == "GET" and parts == ["operations"]:
                    result = service.operations(principal)
                elif self.command == "GET" and parts == ["audit"]:
                    result = service.audit(principal)
                elif self.command == "POST" and parts == ["experiments"]:
                    result = service.plan_experiment(
                        principal, ExperimentPlan.model_validate(self._body()),
                    )
                elif self.command == "GET" and len(parts) == 2 and parts[0] == "experiments":
                    result = service.experiment(principal, parts[1])
                elif (self.command == "POST" and len(parts) == 3 and parts[0] == "experiments"
                      and parts[2] == "predictions"):
                    request = PredictionRegistration.model_validate(self._body())
                    result = service.register_prediction(principal, parts[1],
                                                         request.task_id, request.report_id)
                elif self.command == "GET" and len(parts) == 2 and parts[0] == "predictions":
                    result = service.prediction(principal, parts[1])
                elif (self.command == "POST" and len(parts) == 3 and parts[0] == "predictions"
                      and parts[2] == "observations"):
                    result = service.observe(principal, parts[1],
                                             ObservationInput.model_validate(self._body()))
                elif self.command == "POST" and parts == ["controls"]:
                    request = Control.model_validate(self._body())
                    result = service.control(principal, request.kind, request.enabled, request.reason)
                elif (self.command == "POST" and len(parts) == 3 and parts[0] == "calls"
                      and parts[2] == "reconcile"):
                    result = service.reconcile(principal, parts[1],
                                               CostRequest.model_validate(self._body()))
                if result is None:
                    raise KeyError("route")
                service.identities.audit(principal, "http:request", outcome="success",
                                         request_id=request_id)
                self._send(200, {"request_id": request_id, "data": result})
            except (KeyError, ValueError, PermissionError, BudgetExceeded) as exc:
                status = (401 if isinstance(exc, AuthenticationError) else
                          403 if isinstance(exc, PermissionError) else
                          429 if isinstance(exc, BudgetExceeded) else
                          429 if isinstance(exc, LoginThrottled) else
                          409 if isinstance(exc, SettingsConflict) else
                          404 if isinstance(exc, KeyError) else 400)
                if principal is not None:
                    service.identities.audit(principal, "http:request", outcome=type(exc).__name__,
                                             request_id=request_id)
                fields = []
                if isinstance(exc, InputError):
                    fields = [{"field": exc.field, "message": exc.message}]
                elif isinstance(exc, ValidationError):
                    safe_messages = {
                        "missing": "请填写此字段。", "extra_forbidden": "此字段不支持，请移除。",
                        "int_type": "请输入整数。", "int_parsing": "请输入整数。",
                        "literal_error": "请选择支持的选项。", "string_pattern_mismatch": "格式不符合要求。",
                        "finite_number": "请输入有限数值。", "greater_than": "数值必须大于下限。",
                        "greater_than_equal": "数值低于允许下限。", "less_than_equal": "数值超过允许上限。",
                    }
                    for item in exc.errors(include_input=False, include_url=False):
                        domain_error = item.get("ctx", {}).get("error")
                        field = ".".join(str(part) for part in item["loc"])
                        if isinstance(domain_error, InputError):
                            field = ".".join(filter(None, (field, domain_error.field)))
                        fields.append({
                            "field": field,
                            "message": domain_error.message if isinstance(domain_error, InputError)
                            else safe_messages.get(item["type"], "字段值不符合要求，请核对格式和范围。"),
                        })
                self._send(status, {"request_id": request_id, "error": type(exc).__name__,
                                    **({"fields": fields} if fields else {})})
            except Exception:
                self._send(500, {"request_id": request_id, "error": "InternalError"})
            finally:
                AUDIT_REQUEST.reset(audit_token)

        do_GET = _request
        do_POST = _request

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def __init__(self):
            self.slots = threading.BoundedSemaphore(16)
            self.login_slots = threading.BoundedSemaphore(2)
            super().__init__(("127.0.0.1", port), Handler)

        def process_request(self, request, client_address):
            if not self.slots.acquire(blocking=False):
                request.close()
                return
            try:
                super().process_request(request, client_address)
            except BaseException:
                self.slots.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self.slots.release()

        def server_close(self):
            service.execution.close()
            if demos is not None:
                demos.close()
            super().server_close()

    return Server()
