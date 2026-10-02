from __future__ import annotations

import time
from pathlib import Path

import httpx

from .config import Settings


class OpenBaoClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openbao_addr:
            raise RuntimeError("OPENBAO_ADDR is required for OpenBao secret sources")
        if not settings.openbao_role_id or not settings.openbao_secret_id:
            raise RuntimeError("OPENBAO_ROLE_ID and OPENBAO_SECRET_ID are required")
        self.settings = settings
        self.client = httpx.Client(timeout=10, trust_env=False)
        self._token: str | None = None
        self._expires_at = 0.0

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if token:
            headers["X-Vault-Token"] = token
        if self.settings.openbao_namespace:
            headers["X-Vault-Namespace"] = self.settings.openbao_namespace
        return headers

    def _login(self) -> str:
        now = time.monotonic()
        if self._token and now < self._expires_at:
            return self._token
        url = (
            f"{self.settings.openbao_addr.rstrip('/')}/v1/auth/"
            f"{self.settings.openbao_auth_mount}/login"
        )
        response = self.client.post(
            url,
            json={
                "role_id": self.settings.openbao_role_id,
                "secret_id": self.settings.openbao_secret_id,
            },
            headers=self._headers(),
        )
        response.raise_for_status()
        payload = response.json()["auth"]
        self._token = payload["client_token"]
        lease = int(payload.get("lease_duration") or 300)
        self._expires_at = now + max(30, lease - 30)
        return self._token

    def _read_kv2_data(self, path: str) -> dict[str, object]:
        token = self._login()
        url = (
            f"{self.settings.openbao_addr.rstrip('/')}/v1/"
            f"{self.settings.openbao_kv_mount}/data/{path.lstrip('/')}"
        )
        response = self.client.get(url, headers=self._headers(token))
        response.raise_for_status()
        data = response.json()["data"]["data"]
        if not isinstance(data, dict):
            raise RuntimeError(f"OpenBao data at '{path}' is invalid")
        return data

    def read_kv2(self, path: str, field: str) -> str:
        data = self._read_kv2_data(path)
        if field not in data:
            raise RuntimeError(f"OpenBao field '{field}' is missing at '{path}'")
        value = data[field]
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"OpenBao field '{field}' must be a non-empty string")
        return value

    def read_kv2_optional(self, path: str, field: str) -> str | None:
        data = self._read_kv2_data(path)
        value = data.get(field)
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise RuntimeError(f"OpenBao field '{field}' must be a string")
        return value


class SecretResolver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._openbao: OpenBaoClient | None = None

    @property
    def openbao(self) -> OpenBaoClient:
        if self._openbao is None:
            self._openbao = OpenBaoClient(self.settings)
        return self._openbao

    def github_token(self) -> str:
        if self.settings.github_token_source == "env":
            if not self.settings.github_token:
                raise RuntimeError("GITHUB_TOKEN or GITHUB_TOKEN_FILE is required")
            return self.settings.github_token
        return self.openbao.read_kv2(
            self.settings.openbao_github_path,
            self.settings.openbao_github_field,
        )

    def signing_key(self) -> str:
        if self.settings.signing_key_source == "file":
            if not self.settings.signing_key_file:
                raise RuntimeError("SIGNING_KEY_FILE is required")
            return Path(self.settings.signing_key_file).read_text(encoding="utf-8")
        return self.openbao.read_kv2(
            self.settings.openbao_signing_path,
            self.settings.openbao_signing_field,
        )

    def signing_passphrase(self) -> str | None:
        if self.settings.signing_format != "openpgp":
            return None
        if self.settings.signing_key_source != "openbao":
            return None
        return self.openbao.read_kv2_optional(
            self.settings.openbao_signing_path,
            self.settings.openbao_signing_passphrase_field,
        )
