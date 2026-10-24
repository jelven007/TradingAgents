"""Isolated, auditable local research execution around the compatible graph SDK."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import tradingagents
from tradingagents.domain.quality import AllocationInput, ResearchPolicy, check_research
from tradingagents.domain.research import ResearchMandate
from tradingagents.infrastructure.artifacts import (
    component,
    digest,
    json_bytes,
    utc_now,
    write_json_once,
    write_once,
)
from tradingagents.infrastructure.evidence import EvidenceRecorder, capture_evidence, verify_bundle


@dataclass(frozen=True)
class RunScope:
    workspace: str
    experiment: str
    task: str
    attempt: str

    def path(self, root: Path) -> Path:
        return Path(root).joinpath(*(component(value) for value in (
            self.workspace, self.experiment, self.task, self.attempt,
        )))


@dataclass(frozen=True)
class RunResult:
    path: Path
    manifest_sha256: str
    evidence_sha256: str
    rating: str


def implementation_versions() -> dict:
    package = Path(tradingagents.__file__).parent
    sources = {p.relative_to(package).as_posix(): digest(p.read_bytes())
               for p in sorted(package.rglob("*.py"))}
    return {
        "package_version": tradingagents.__version__, "source_sha256": digest(json_bytes(sources)),
        "sources": sources,
        "dependencies": {name: version(name) for name in
                         ("langchain-core", "langgraph", "pydantic", "pandas", "yfinance")},
    }


def execute_research(
    root: Path, scope: RunScope, mandate: ResearchMandate, config: dict, *,
    selected_analysts=("market", "social", "news", "fundamentals"),
    portfolio=None, callbacks=None, graph_factory=None, allocation: AllocationInput | None = None,
    expected_implementation: dict | None = None,
) -> RunResult:
    """Every attempt is fresh; retries cannot inherit unaccepted output or memory.

    Local paths and credentials belong to trusted operator configuration. Input
    manifests store safe model/vendor settings plus a hash of the full config.
    """
    mandate = ResearchMandate.model_validate(mandate)
    mandate.validate_run(mandate.ticker, mandate.analysis_date, mandate.asset_type)
    policy = ResearchPolicy.model_validate(config.get("research_policy", {}))
    if allocation is not None:
        allocation = AllocationInput.model_validate(allocation)
    implementation = implementation_versions()
    if expected_implementation is not None and implementation != expected_implementation:
        raise ValueError("implementation changed since task submission")
    path = scope.path(root)
    path.mkdir(parents=True, exist_ok=False)
    cfg = deepcopy(config)
    config_hash = digest(json_bytes(cfg))
    cfg.update({
        "research_mandate": mandate.model_dump(mode="json"),
        "results_dir": str(path / "results"), "data_cache_dir": str(path / "cache"),
        "memory_log_path": str(path / "memory" / "decisions.md"),
        "checkpoint_enabled": False, "settle_during_run": False,
    })
    recorder = EvidenceRecorder(path / "evidence", cfg.get("source_licenses"))
    input_hash = write_json_once(path / "input.json", {
        "schema_version": 1, "created_at": utc_now(),
        "scope": vars(scope), "mandate": mandate.model_dump(mode="json"),
        "config_sha256": config_hash, "analysts": list(selected_analysts),
        "portfolio": portfolio.model_dump(mode="json") if portfolio is not None else None,
        "allocation": allocation.model_dump(mode="json") if allocation is not None else None,
        "policy": policy.model_dump(mode="json"),
    })
    if graph_factory is None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        graph_factory = TradingAgentsGraph
    try:
        with capture_evidence(recorder):
            graph = graph_factory(config=cfg, selected_analysts=selected_analysts,
                                  callbacks=list(callbacks or []))
            state, rating = graph.propagate(mandate.ticker, mandate.analysis_date,
                                           asset_type=mandate.asset_type, portfolio=portfolio)
            graph.save_reports(state, mandate.ticker, path / "report")
        _, evidence_hash = recorder.seal()
        verify_bundle(path / "evidence", evidence_hash)
        quality = check_research(mandate, state, path / "evidence", evidence_hash,
                                 policy, allocation=allocation)
        quality_hash = write_json_once(path / "quality.json", quality)
        write_once(path / "report" / "quality.md", (
            "# Independent research quality checks\n\n"
            f"Status: **{quality['status']}**. This run is a draft, pending human review.\n\n"
            + "\n".join(f"- [{i['severity']}] {i['code']}: {i['detail']}"
                        for i in quality["issues"])
            + "\n\nGeneral research checks do not authorize orders or certify investment performance.\n"
        ).encode())
        files = {}
        for file in sorted((path / "report").rglob("*")):
            if file.is_file():
                files[file.relative_to(path).as_posix()] = digest(file.read_bytes())
        # Persist JSON-compatible decision state; conversation objects remain in
        # the SDK/checkpoints and are not silently stringified into this contract.
        state_hash = write_json_once(path / "state.json",
                                     {k: v for k, v in state.items() if k != "messages"})
        files.update({"input.json": input_hash, "state.json": state_hash,
                      "evidence/manifest.json": evidence_hash, "quality.json": quality_hash})
        if implementation_versions() != implementation:
            raise ValueError("implementation changed during execution")
        manifest_hash = write_json_once(path / "run.json", {
            "schema_version": 1, "status": "completed", "completed_at": utc_now(),
            "scope": vars(scope), "rating": rating, "files": files,
            "settings": graph.run_settings(),
            "implementation": implementation,
        })
        return RunResult(path, manifest_hash, evidence_hash, rating)
    except Exception as exc:
        # Exception strings may contain provider URLs/credentials.
        write_json_once(path / "failure.json", {"failed_at": utc_now(),
                                               "error_type": type(exc).__name__})
        raise
