"""Public workspace model configuration; secrets are accepted only in write DTOs."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

TIERS = ("quick", "deep")
PROVIDERS = (
    "openai", "deepseek", "qwen-cn", "qwen", "glm-cn", "glm", "minimax-cn", "minimax",
    "kimi", "anthropic", "google", "openrouter", "xai", "mistral", "groq", "nvidia",
    "azure", "ollama", "openai_compatible",
)
NATIVE_ENDPOINTS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com",
}


def default_endpoint(provider: str) -> str:
    if provider in NATIVE_ENDPOINTS:
        return NATIVE_ENDPOINTS[provider]
    from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS
    spec = OPENAI_COMPATIBLE_PROVIDERS.get(provider)
    return (spec.base_url or "") if spec else ""


def validate_endpoint(provider: str, value: str) -> str:
    """Public HTTPS endpoints, or explicit loopback HTTP for local model runtimes."""
    value = value.strip().rstrip("/")
    url = urlsplit(value)
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or any(char.isspace() for char in value) or "\\" in value):
        raise ValueError("model endpoint must be an absolute URL without credentials or query")
    host = url.hostname.lower()
    local = host in {"localhost", "127.0.0.1", "::1"}
    if local:
        if provider not in {"ollama", "openai_compatible"} or url.scheme != "http":
            raise ValueError("loopback endpoint requires a local compatible provider")
        if not url.port or url.port <= 1023:
            raise ValueError("local model endpoint requires an explicit port above 1023")
    else:
        if url.scheme != "https" or host.endswith((".localhost", ".local")):
            raise ValueError("hosted model endpoint requires public HTTPS")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError("private model endpoint is unsupported")
        if url.port not in {None, 443}:
            raise ValueError("hosted model endpoint requires HTTPS port 443")
    # Gemini's SDK owns its transport; keep it on its official endpoint.
    if provider == "google" and value != NATIVE_ENDPOINTS["google"]:
        raise ValueError("Google requires its official endpoint")
    return value


class TierSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(default="", max_length=1000)
    api_key: SecretStr | None = None
    clear_api_key: bool = Field(default=False, strict=True)
    api_version: str = Field(default="", max_length=80)

    @field_validator("provider")
    @classmethod
    def provider_known(cls, value):
        if value not in PROVIDERS:
            raise ValueError("unsupported settings provider")
        return value

    @field_validator("model", "api_version")
    @classmethod
    def identifier(cls, value, info):
        value = value.strip()
        if info.field_name == "model" and not value:
            raise ValueError("model identifier is required")
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("model and API version must be identifiers")
        return value

    @field_validator("api_key")
    @classmethod
    def key_valid(cls, value):
        if value is None or not value.get_secret_value().strip():
            return None
        raw = value.get_secret_value().strip()
        if len(raw) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in raw):
            raise ValueError("invalid API key")
        return SecretStr(raw)

    @model_validator(mode="after")
    def endpoint_and_key(self):
        validate_endpoint(self.provider, self.base_url or default_endpoint(self.provider))
        if self.clear_api_key and self.api_key:
            raise ValueError("cannot replace and clear a key together")
        if self.provider == "azure" and not self.api_version:
            raise ValueError("Azure requires an API version")
        return self

    def public(self) -> dict:
        return {
            "provider": self.provider, "model": self.model,
            "base_url": validate_endpoint(
                self.provider, self.base_url or default_endpoint(self.provider),
            ),
            "api_version": self.api_version,
        }


class ModelSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_version: int = Field(ge=0, strict=True)
    quick: TierSettings
    deep: TierSettings


class ModelProbeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_version: int = Field(ge=0, strict=True)
    tier: str
    settings: TierSettings

    @field_validator("tier")
    @classmethod
    def tier_known(cls, value):
        if value not in TIERS:
            raise ValueError("unknown model tier")
        return value


class SettingsConflict(ValueError):
    """A second editor saved a newer revision."""
