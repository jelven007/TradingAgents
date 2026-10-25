"""Small immutable, content-addressed artifacts for the local research service."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def component(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value):
        raise ValueError("identifier must be 1-96 ASCII letters, digits, underscores or hyphens")
    return value


def json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_once(path: Path, content: bytes) -> str:
    """Publish atomically, never overwrite; fsync both content and directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temp.unlink(missing_ok=True)
    return digest(content)


def write_json_once(path: Path, value) -> str:
    return write_once(path, json_bytes(value))


def read_verified(path: Path, expected_hash: str) -> bytes:
    content = Path(path).read_bytes()
    if digest(content) != expected_hash:
        raise ValueError(f"artifact integrity check failed: {Path(path).name}")
    return content


def hash_component(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid SHA-256 reference")
    return value
