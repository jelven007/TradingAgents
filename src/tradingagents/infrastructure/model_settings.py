"""Immutable model revisions with credentials encrypted separately from task inputs."""

from __future__ import annotations

import json
import os
import time
import uuid
from copy import deepcopy
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from tradingagents.domain.model_settings import (
    TIERS,
    ModelSettingsInput,
    SettingsConflict,
    TierSettings,
    default_endpoint,
)
from tradingagents.infrastructure.artifacts import digest, json_bytes
from tradingagents.infrastructure.reports import database
from tradingagents.llm_clients.factory import tier_provider


class ModelSettingsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.key_path = self.path.with_name(self.path.name + ".model-key")
        with database(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS model_credentials (
                    id TEXT PRIMARY KEY, workspace TEXT NOT NULL, ciphertext TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_revisions (
                    id TEXT PRIMARY KEY, workspace TEXT NOT NULL, version INTEGER NOT NULL,
                    payload TEXT NOT NULL, payload_hash TEXT NOT NULL, actor TEXT NOT NULL,
                    created REAL NOT NULL, UNIQUE(workspace,version)
                );
                CREATE TABLE IF NOT EXISTS model_active (
                    workspace TEXT PRIMARY KEY, revision TEXT NOT NULL REFERENCES model_revisions(id)
                );
                CREATE TRIGGER IF NOT EXISTS model_revision_no_update BEFORE UPDATE ON model_revisions
                    BEGIN SELECT RAISE(ABORT, 'model revisions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS model_revision_no_delete BEFORE DELETE ON model_revisions
                    BEGIN SELECT RAISE(ABORT, 'model revisions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS model_credential_no_update BEFORE UPDATE ON model_credentials
                    BEGIN SELECT RAISE(ABORT, 'model credentials are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS model_credential_no_delete BEFORE DELETE ON model_credentials
                    BEGIN SELECT RAISE(ABORT, 'model credentials are immutable'); END;
            """)

    def _cipher(self, *, create=False):
        if create and not self.key_path.exists():
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as file:
                    file.write(Fernet.generate_key())
                    file.flush()
                    os.fsync(file.fileno())
        if self.key_path.is_symlink() or self.key_path.stat().st_mode & 0o077:
            raise ValueError("model credential key requires private file permissions")
        return Fernet(self.key_path.read_bytes())

    @staticmethod
    def _decode(row):
        payload = json.loads(row["payload"])
        if digest(json_bytes(payload)) != row["payload_hash"]:
            raise ValueError("model revision integrity failed")
        for tier in TIERS:
            record = payload[tier]
            TierSettings.model_validate({k: v for k, v in record.items() if k != "credential_id"})
        return {"id": row["id"], "version": row["version"], "created": row["created"],
                "workspace": row["workspace"], "tiers": payload}

    def _active(self, db, workspace):
        row = db.execute("""SELECT r.* FROM model_active a JOIN model_revisions r ON r.id=a.revision
            WHERE a.workspace=?""", (workspace,)).fetchone()
        return self._decode(row) if row else None

    def credential(self, credential_id: str | None, workspace: str) -> str | None:
        if not credential_id:
            return None
        with database(self.path) as db:
            row = db.execute("SELECT ciphertext FROM model_credentials WHERE id=? AND workspace=?",
                             (credential_id, workspace)).fetchone()
        if row is None:
            raise ValueError("model credential reference is invalid")
        try:
            return self._cipher().decrypt(row["ciphertext"].encode()).decode()
        except (FileNotFoundError, InvalidToken) as exc:
            raise ValueError("model credential must be configured again") from exc

    def public(self, workspace: str, baseline: dict):
        with database(self.path) as db:
            active = self._active(db, workspace)
        tiers = {}
        for tier in TIERS:
            if active:
                record = active["tiers"][tier]
                try:
                    present = bool(self.credential(record.get("credential_id"), workspace))
                except ValueError:
                    present = False
                tiers[tier] = {k: v for k, v in record.items() if k != "credential_id"}
                tiers[tier]["api_key_configured"] = present
            else:
                provider = tier_provider(baseline, tier)
                tiers[tier] = {
                    "provider": provider, "model": baseline[f"{tier}_think_llm"],
                    "base_url": baseline.get(f"{tier}_think_backend_url") or (
                        baseline.get("backend_url") if provider == baseline["llm_provider"] else None
                    ) or default_endpoint(provider),
                    "api_version": "", "api_key_configured": False,
                }
        return {"version": active["version"] if active else 0,
                "saved_at": active["created"] if active else None, **tiers}

    def _check_version(self, db, workspace, expected_version):
        active = self._active(db, workspace)
        if expected_version != (active["version"] if active else 0):
            raise SettingsConflict("model configuration changed; reload before saving")
        return active

    def _tier_draft(self, workspace, draft, previous):
        record = draft.public()
        key = draft.api_key.get_secret_value() if draft.api_key else None
        # Keep only when the credential destination remains identical.
        retain = not draft.clear_api_key and not key and all(
            previous.get(k) == record[k] for k in ("provider", "base_url")
        )
        record["credential_id"] = previous.get("credential_id") if retain else None
        if retain:
            key = self.credential(record["credential_id"], workspace)
        return record, key

    def _draft(self, db, workspace: str, data: ModelSettingsInput):
        active = self._check_version(db, workspace, data.expected_version)
        records, keys = {}, {}
        for tier in TIERS:
            draft = getattr(data, tier)
            previous = active["tiers"][tier] if active else {}
            records[tier], keys[tier] = self._tier_draft(workspace, draft, previous)
        return records, keys

    def probe_draft(self, workspace, data):
        with database(self.path) as db:
            active = self._check_version(db, workspace, data.expected_version)
            previous = active["tiers"][data.tier] if active else {}
            return self._tier_draft(workspace, data.settings, previous)

    def save(self, workspace: str, data: ModelSettingsInput, actor: str):
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            records, keys = self._draft(db, workspace, data)
            for tier in TIERS:
                if keys[tier] and not records[tier]["credential_id"]:
                    credential_id = uuid.uuid4().hex
                    ciphertext = self._cipher(create=True).encrypt(keys[tier].encode()).decode()
                    db.execute("INSERT INTO model_credentials VALUES (?,?,?)",
                               (credential_id, workspace, ciphertext))
                    records[tier]["credential_id"] = credential_id
            revision = uuid.uuid4().hex
            payload = json_bytes(records)
            db.execute("INSERT INTO model_revisions VALUES (?,?,?,?,?,?,?)",
                       (revision, workspace, data.expected_version + 1, payload.decode(),
                        digest(payload), actor, time.time()))
            db.execute("INSERT OR REPLACE INTO model_active VALUES (?,?)", (workspace, revision))

    def effective(self, workspace: str, config: dict) -> dict:
        result = deepcopy(config)
        with database(self.path) as db:
            active = self._active(db, workspace)
        if active:
            result["model_settings_revision"] = active["id"]
            result["model_settings_workspace"] = workspace
            for tier in TIERS:
                record = active["tiers"][tier]
                result[f"{tier}_think_provider"] = record["provider"]
                result[f"{tier}_think_llm"] = record["model"]
                result[f"{tier}_think_backend_url"] = record["base_url"]
                result[f"{tier}_think_api_version"] = record["api_version"]
        return result

    def frozen_credentials(self, config: dict) -> dict:
        revision = config.get("model_settings_revision")
        if not revision:
            return {}
        workspace = config["model_settings_workspace"]
        with database(self.path) as db:
            row = db.execute("SELECT * FROM model_revisions WHERE id=? AND workspace=?",
                             (revision, workspace)).fetchone()
        if row is None:
            raise ValueError("model revision is unavailable")
        active = self._decode(row)
        keys = {}
        for tier in TIERS:
            record = active["tiers"][tier]
            if (tier_provider(config, tier), config[f"{tier}_think_llm"],
                config[f"{tier}_think_backend_url"]) != (
                    record["provider"], record["model"], record["base_url"],
            ):
                raise ValueError("task model configuration differs from its frozen revision")
            keys[tier] = self.credential(record.get("credential_id"), workspace)
        return keys

    def validate(self):
        with database(self.path) as db:
            for row in db.execute("SELECT * FROM model_revisions"):
                record = self._decode(row)
                for tier in record["tiers"].values():
                    if tier.get("credential_id") and not db.execute(
                        "SELECT id FROM model_credentials WHERE id=? AND workspace=?",
                        (tier["credential_id"], record["workspace"]),
                    ).fetchone():
                        raise ValueError("model credential reference is invalid")
