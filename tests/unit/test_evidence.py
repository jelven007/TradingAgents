import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

from tradingagents.application.runs import RunScope
from tradingagents.dataflows import router
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.infrastructure.artifacts import write_once
from tradingagents.infrastructure.evidence import (
    EvidenceRecorder,
    capture_evidence,
    record_evidence,
    verify_bundle,
)


def test_concurrent_capture_deduplicates_bytes_but_keeps_calls(tmp_path):
    recorder = EvidenceRecorder(tmp_path, {"test": "internal-test"})
    with capture_evidence(recorder), ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(copy_context().run, record_evidence, "test", "prices",
                               {"ticker": "NVDA"}, "identical actual content") for _ in range(24)]
        for future in futures:
            future.result()
    _, ref = recorder.seal()
    manifest = verify_bundle(tmp_path, ref)
    assert len(manifest["records"]) == 24
    assert len(list((tmp_path / "blobs").glob("*.json"))) == 1
    for record in manifest["records"]:
        assert record["known_at"] is None and record["fetched_at"] is None
        assert record["license"] == "internal-test"
    # Leaving the context does not contaminate the previous bundle.
    record_evidence("test", "outside", {}, "not retained")
    assert len(verify_bundle(tmp_path, ref)["records"]) == 24
    with pytest.raises(RuntimeError, match="sealed"):
        recorder.record("test", "late", {}, "x")


@pytest.mark.parametrize("target", ["manifest", "content"])
def test_altered_evidence_is_rejected(tmp_path, target):
    recorder = EvidenceRecorder(tmp_path)
    recorder.record("yfinance", "prices", {}, "actual")
    manifest, ref = recorder.seal()
    if target == "manifest":
        (tmp_path / "manifest.json").write_text('{"records":[]}')
    else:
        content_hash = manifest["records"][0]["content_sha256"]
        (tmp_path / "blobs" / f"{content_hash}.json").write_text('"forged"')
    with pytest.raises(ValueError, match="integrity"):
        verify_bundle(tmp_path, ref)


def test_failed_write_cannot_be_sealed_as_complete(tmp_path, monkeypatch):
    import tradingagents.infrastructure.evidence as module

    def fail(*args):
        raise OSError("disk full")

    recorder = EvidenceRecorder(tmp_path)
    monkeypatch.setattr(module, "write_once", fail)
    with pytest.raises(OSError):
        recorder.record("test", "prices", {}, "actual")
    with pytest.raises(RuntimeError, match="incomplete"):
        recorder.seal()


def test_vendor_fallback_keeps_actual_source_and_failure_type(tmp_path, monkeypatch):
    def unavailable(*args):
        raise VendorUnavailableError("credentials must not appear in capture")

    monkeypatch.setitem(router.VENDOR_METHODS["get_stock_data"], "alpha_vantage", unavailable)
    monkeypatch.setitem(router.VENDOR_METHODS["get_stock_data"], "yfinance", lambda *a: "prices")
    recorder = EvidenceRecorder(tmp_path)
    with capture_evidence(recorder), run_config(
        {"tool_vendors": {"get_stock_data": "alpha_vantage,yfinance"}},
    ):
        assert router.route_to_vendor("get_stock_data", "NVDA", "2026-01-01", "2026-01-09") == "prices"
    manifest, ref = recorder.seal()
    assert [r["source"] for r in manifest["records"]] == ["alpha_vantage", "yfinance"]
    assert [r["status"] for r in manifest["records"]] == ["error", "returned"]
    error_ref = manifest["records"][0]["content_sha256"]
    error = json.loads((tmp_path / "blobs" / f"{error_ref}.json").read_bytes())
    assert error == {"error_type": "VendorUnavailableError"}
    verify_bundle(tmp_path, ref)


@pytest.mark.parametrize("part", ["..", "/tmp", "a/b", "", "a.b", "x" * 97])
def test_run_scope_cannot_escape_storage(tmp_path, part):
    with pytest.raises(ValueError, match="identifier"):
        RunScope("work", part, "task", "attempt").path(tmp_path)


def test_immutable_file_is_not_overwritten(tmp_path):
    path = tmp_path / "object"
    write_once(path, b"original")
    with pytest.raises(FileExistsError):
        write_once(path, b"replacement")
    assert path.read_bytes() == b"original"
