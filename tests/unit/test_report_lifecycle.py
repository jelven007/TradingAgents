import json
import sqlite3

import pytest

from tradingagents.infrastructure.artifacts import write_json_once, write_once
from tradingagents.infrastructure.evidence import EvidenceRecorder
from tradingagents.infrastructure.reports import ReportStore, verify_run


def draft(path, *, blocked=False, valid_until="2099-01-01", workspace="research"):
    path.mkdir(parents=True)
    recorder = EvidenceRecorder(path / "evidence")
    recorder.record("test", "prices", {}, "actual")
    _, evidence_hash = recorder.seal()
    files = {
        "evidence/manifest.json": evidence_hash,
        "input.json": write_json_once(path / "input.json", {
            "scope": {"workspace": workspace}, "mandate": {"valid_until": valid_until},
        }),
        "quality.json": write_json_once(path / "quality.json", {
            "status": "blocked" if blocked else "needs_review",
            "issues": [{"code": "missing_price" if blocked else "unverified_narrative",
                        "severity": "block" if blocked else "review"}],
        }),
        "report.md": write_once(path / "report.md", b"Fixed report content"),
    }
    ref = write_json_once(path / "run.json", {"status": "completed", "files": files})
    return ref


def test_fixed_version_review_publish_withdraw_and_revision(tmp_path):
    path = tmp_path / "run"
    ref = draft(path)
    store = ReportStore(tmp_path / "db.sqlite")
    report = store.register(path, ref, "analyst")
    with pytest.raises(PermissionError, match="own report"):
        store.transition(report, "approved", "analyst", "self-review",
                         acknowledgements=["unverified_narrative"])
    with pytest.raises(ValueError, match="acknowledge"):
        store.transition(report, "approved", "reviewer", "verified")
    with pytest.raises(ValueError, match="invalid transition"):
        store.transition(report, "published", "publisher", "release")
    store.transition(report, "approved", "reviewer", "claims independently checked",
                     acknowledgements=["unverified_narrative"])
    store.transition(report, "published", "publisher", "internal distribution")
    state = store.transition(report, "withdrawn", "reviewer", "new material event")
    assert [e["action"] for e in state["events"]] == ["draft", "approved", "published", "withdrawn"]
    with pytest.raises(ValueError, match="invalid transition"):
        store.transition(report, "published", "publisher", "again")
    second = tmp_path / "revision"
    second_ref = draft(second)
    revision = store.register(second, second_ref, "analyst", supersedes=report)
    assert store.get(revision)["supersedes"] == report
    assert store.get(report)["manifest_hash"] == ref
    verify_run(path, ref)


@pytest.mark.parametrize("action", ["approved", "published"])
def test_tampered_report_never_reaches_approval_or_publication(tmp_path, action):
    path = tmp_path / "run"
    store = ReportStore(tmp_path / "db.sqlite")
    report = store.register(path, draft(path), "analyst")
    if action == "published":
        store.transition(report, "approved", "reviewer", "checked",
                         acknowledgements=["unverified_narrative"])
    (path / "report.md").write_text("swapped conclusion")
    with pytest.raises(ValueError, match="integrity"):
        store.transition(report, action, "reviewer", "checked",
                         acknowledgements=["unverified_narrative"])


@pytest.mark.parametrize(("options", "error"), [
    ({"blocked": True}, "hard quality"), ({"valid_until": "2000-01-01"}, "expired"),
])
def test_reviewer_cannot_override_hard_failure_or_expiry(tmp_path, options, error):
    path = tmp_path / "run"
    store = ReportStore(tmp_path / "db.sqlite")
    report = store.register(path, draft(path, **options), "analyst")
    with pytest.raises(ValueError, match=error):
        store.transition(report, "approved", "reviewer", "accept all",
                         acknowledgements=["missing_price", "unverified_narrative"])


def test_versions_and_audit_events_reject_mutation(tmp_path):
    path = tmp_path / "run"
    store = ReportStore(tmp_path / "db.sqlite")
    report = store.register(path, draft(path), "analyst")
    with sqlite3.connect(store.path) as db:
        for statement in ("UPDATE reports SET author='x'", "DELETE FROM reports",
                          "UPDATE report_events SET actor='x'", "DELETE FROM report_events"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute(statement)
    assert store.get(report)["author"] == "analyst"


def test_revision_cannot_link_another_workspace(tmp_path):
    store = ReportStore(tmp_path / "db.sqlite")
    path = tmp_path / "first"
    report = store.register(path, draft(path), "analyst")
    other = tmp_path / "other"
    with pytest.raises(ValueError, match="superseded"):
        store.register(other, draft(other, workspace="other"), "analyst", supersedes=report)


def test_audit_chain_detects_edit_even_if_trigger_is_removed(tmp_path):
    path = tmp_path / "run"
    store = ReportStore(tmp_path / "db.sqlite")
    report = store.register(path, draft(path), "analyst")
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TRIGGER report_events_no_update")
        db.execute("UPDATE report_events SET acknowledgements=?", (json.dumps(["forged"]),))
    with pytest.raises(ValueError, match="audit integrity"):
        store.get(report)
