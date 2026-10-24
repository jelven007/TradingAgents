"""Bounded JSON HTTP control plane, intentionally bound to IPv4 loopback."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.application.service import ResearchService
from tradingagents.domain.evaluation import ExperimentPlan, ObservationInput
from tradingagents.domain.service import CostRequest, ReviewRequest, SubmitRequest
from tradingagents.infrastructure.artifacts import json_bytes
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


def make_server(service: ResearchService, *, port=0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(5)
            super().setup()

        def log_message(self, format, *args):
            pass  # Audit is structured; never log bearer headers or request bodies.

        def _send(self, status, value):
            content = json_bytes(value)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

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

        def _request(self):
            request_id = uuid.uuid4().hex
            audit_token = AUDIT_REQUEST.set(request_id)
            principal = None
            try:
                scheme, _, token = self.headers.get("Authorization", "").partition(" ")
                if scheme.lower() != "bearer":
                    raise AuthenticationError("bearer credential required")
                principal = service.identities.authenticate(token)
                parts = self.path.strip("/").split("/")
                result = None
                if self.command == "POST" and parts == ["tasks"]:
                    result = service.submit(
                        principal, SubmitRequest.model_validate(self._body()),
                        self.headers.get("Idempotency-Key", ""),
                    )
                elif len(parts) == 2 and parts[0] == "tasks" and self.command == "GET":
                    result = service.task(principal, parts[1])
                elif len(parts) == 3 and parts[0] == "tasks" and self.command == "POST":
                    if parts[2] == "cancel":
                        Registration.model_validate(self._body())
                        result = service.cancel(principal, parts[1])
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
                          404 if isinstance(exc, KeyError) else 400)
                if principal is not None:
                    service.identities.audit(principal, "http:request", outcome=type(exc).__name__,
                                             request_id=request_id)
                self._send(status, {"request_id": request_id, "error": type(exc).__name__})
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

    return Server()
