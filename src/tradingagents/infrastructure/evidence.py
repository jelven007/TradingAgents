"""Capture the exact consumed data, without claiming undocumented publication times."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from tradingagents.infrastructure.artifacts import (
    digest,
    hash_component,
    json_bytes,
    read_verified,
    utc_now,
    write_json_once,
    write_once,
)

_recorder: ContextVar[EvidenceRecorder | None] = ContextVar("evidence_recorder", default=None)


class EvidenceRecorder:
    def __init__(self, path: Path, licenses: dict[str, str] | None = None):
        self.path = Path(path)
        self.licenses = dict(licenses or {})
        self._lock = threading.Lock()
        self._records: list[dict] = []
        self._closed = False
        self._failure = False

    def record(self, source: str, method: str, inputs, output, *, status="returned") -> None:
        with self._lock:
            try:
                if self._closed:
                    raise RuntimeError("evidence bundle is sealed")
                content = json_bytes(output)
                content_hash = digest(content)
                blob = self.path / "blobs" / f"{content_hash}.json"
                if blob.exists():
                    read_verified(blob, content_hash)
                else:
                    write_once(blob, content)
                self._records.append({
                    "source": source, "method": method, "inputs": inputs,
                    "content_sha256": content_hash, "status": status,
                    "observed_at": utc_now(),
                    # Capture time does not prove when a vendor fetched or published data.
                    "fetched_at": None, "known_at": None, "published_at": None,
                    "license": self.licenses.get(source, "unknown"),
                })
            except Exception:
                self._failure = True
                raise

    def seal(self) -> tuple[dict, str]:
        with self._lock:
            if self._failure:
                raise RuntimeError("incomplete evidence capture")
            if self._closed:
                raise RuntimeError("evidence bundle is sealed")
            manifest = {
                "schema_version": 1, "sealed_at": utc_now(),
                "time_semantics": "exact consumed output; publication and cache origin times unknown",
                "records": self._records.copy(),
            }
            ref = write_json_once(self.path / "manifest.json", manifest)
            self._closed = True
            return manifest, ref


@contextmanager
def capture_evidence(recorder: EvidenceRecorder):
    token = _recorder.set(recorder)
    try:
        yield recorder
    finally:
        _recorder.reset(token)


def record_evidence(source: str, method: str, inputs, output, *, status="returned") -> None:
    recorder = _recorder.get()
    if recorder is not None:
        recorder.record(source, method, inputs, output, status=status)


def verify_bundle(path: Path, expected_hash: str) -> dict:
    """The expected manifest hash must come from the accepted run/review record."""
    path = Path(path)
    manifest = json.loads(read_verified(path / "manifest.json", expected_hash))
    if manifest["schema_version"] != 1:
        raise ValueError("unsupported evidence schema")
    for record in manifest["records"]:
        ref = hash_component(record["content_sha256"])
        read_verified(path / "blobs" / f"{ref}.json", ref)
    return manifest
