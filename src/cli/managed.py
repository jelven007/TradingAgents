"""Non-interactive managed research commands alongside the compatible CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from tradingagents.application.service import ResearchService
from tradingagents.application.worker import run_one
from tradingagents.domain.evaluation import ExperimentPlan, ObservationInput
from tradingagents.domain.service import CostRequest, ReviewRequest, SubmitRequest
from tradingagents.infrastructure.artifacts import write_once
from tradingagents.infrastructure.recovery import backup, restore
from tradingagents.interfaces.api import make_server

app = typer.Typer(help="Scoped local research tasks, review and recovery.")


@app.callback()
def configure(ctx: typer.Context, db: Path = Path("runtime/research.sqlite"),
              artifacts: Path = Path("runtime/artifacts"), templates: Path | None = None):
    registered = json.loads(templates.read_bytes()) if templates else {}
    ctx.obj = ResearchService(db, artifacts, registered)


def _principal(ctx):
    return ctx.obj.identities.authenticate(os.environ.get("TA_RESEARCH_TOKEN", ""))


def _output(value):
    typer.echo(json.dumps(value, ensure_ascii=False, allow_nan=False))


@app.command("identity-issue")
def identity_issue(ctx: typer.Context, subject: str, workspace: str, scopes: str, token_file: Path,
                   ttl: int = 3600):
    """Trusted local operator: issue a short-lived token into a new private file."""
    if token_file.exists():
        raise typer.BadParameter("token file already exists")
    identity, token = ctx.obj.identities.issue(subject, workspace, scopes.split(","), ttl_seconds=ttl)
    write_once(token_file, token.encode())
    token_file.chmod(0o600)
    _output({"identity_id": identity, "token_file": str(token_file)})


@app.command("identity-revoke")
def identity_revoke(ctx: typer.Context, identity_id: str):
    ctx.obj.identities.revoke(identity_id)
    _output({"revoked": identity_id})


@app.command("submit")
def submit(ctx: typer.Context, request_file: Path, key: str = typer.Option(...)):
    _output(ctx.obj.submit(_principal(ctx), SubmitRequest.model_validate_json(request_file.read_bytes()),
                           key))


@app.command("task")
def task(ctx: typer.Context, task_id: str):
    _output(ctx.obj.task(_principal(ctx), task_id))


@app.command("cancel")
def cancel(ctx: typer.Context, task_id: str):
    _output(ctx.obj.cancel(_principal(ctx), task_id))


@app.command("register")
def register(ctx: typer.Context, task_id: str, supersedes: str | None = None):
    _output(ctx.obj.register(_principal(ctx), task_id, supersedes=supersedes))


@app.command("report")
def report(ctx: typer.Context, report_id: str):
    _output(ctx.obj.report(_principal(ctx), report_id))


@app.command("review")
def review(ctx: typer.Context, report_id: str, action: str, reason: str, acknowledge: str = ""):
    _output(ctx.obj.review(_principal(ctx), report_id, ReviewRequest(
        action=action, reason=reason, acknowledgements=tuple(filter(None, acknowledge.split(","))),
    )))


@app.command("operations")
def operations(ctx: typer.Context):
    _output(ctx.obj.operations(_principal(ctx)))


@app.command("audit")
def audit(ctx: typer.Context):
    _output(ctx.obj.audit(_principal(ctx)))


@app.command("control")
def control(ctx: typer.Context, kind: str, reason: str,
            enabled: bool = typer.Option(..., "--enabled/--no-enabled")):
    _output(ctx.obj.control(_principal(ctx), kind, enabled, reason))


@app.command("reconcile")
def reconcile(ctx: typer.Context, call_id: str, amount_microusd: int, invoice_ref: str):
    _output(ctx.obj.reconcile(_principal(ctx), call_id, CostRequest(
        amount_microusd=amount_microusd, invoice_ref=invoice_ref,
    )))


@app.command("worker")
def worker(ctx: typer.Context, worker_id: str = "local-worker", max_tasks: int = 1,
           concurrency: int = 2):
    """Trusted local operator: process a bounded number of queued tasks."""
    if not 1 <= max_tasks <= 1000 or not 1 <= concurrency <= 32:
        raise typer.BadParameter("bounded task count and concurrency required")
    for _ in range(max_tasks):
        task_id = run_one(ctx.obj.tasks, ctx.obj.root, worker_id, max_concurrency=concurrency)
        if task_id is None:
            break
        _output({"task_id": task_id, "status": ctx.obj.tasks.get(task_id)["status"]})


@app.command("plan")
def plan(ctx: typer.Context, plan_file: Path):
    _output(ctx.obj.plan_experiment(_principal(ctx),
                                   ExperimentPlan.model_validate_json(plan_file.read_bytes())))


@app.command("experiment")
def experiment(ctx: typer.Context, experiment_id: str):
    _output(ctx.obj.experiment(_principal(ctx), experiment_id))


@app.command("predict")
def predict(ctx: typer.Context, experiment_id: str, task_id: str, report_id: str):
    _output(ctx.obj.register_prediction(_principal(ctx), experiment_id, task_id, report_id))


@app.command("prediction")
def prediction(ctx: typer.Context, prediction_id: str):
    _output(ctx.obj.prediction(_principal(ctx), prediction_id))


@app.command("observe")
def observe(ctx: typer.Context, prediction_id: str, observation_file: Path):
    _output(ctx.obj.observe(_principal(ctx), prediction_id,
                           ObservationInput.model_validate_json(observation_file.read_bytes())))


@app.command("serve")
def serve(ctx: typer.Context, port: int = 8765):
    """Start the browser workbench and local JSON API on 127.0.0.1."""
    with make_server(ctx.obj, port=port, browser_accounts=True) as server:
        typer.echo(f"Research API: http://127.0.0.1:{server.server_port}")
        server.serve_forever(poll_interval=0.25)


@app.command("backup")
def backup_command(ctx: typer.Context, destination: Path):
    _output({"backup_sha256": backup(ctx.obj.tasks.path, ctx.obj.root, destination)})


@app.command("restore")
def restore_command(ctx: typer.Context, source: Path, sha256: str, destination: Path):
    _output({"database": str(restore(source, sha256, destination))})
