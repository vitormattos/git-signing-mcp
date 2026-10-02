from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import httpx

from .config import Settings


T = TypeVar("T")


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
        self._lock = threading.Lock()

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if token:
            headers["X-Vault-Token"] = token
        if self.settings.openbao_namespace:
            headers["X-Vault-Namespace"] = self.settings.openbao_namespace
        return headers

    def _login(self) -> str:
        with self._lock:
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

    def read_kv2_data(self, path: str) -> dict[str, object]:
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


class SecretResolver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._openbao: OpenBaoClient | None = None
        self._cache: dict[str, tuple[float, object]] = {}
        self._cache_lock = threading.Lock()

    @property
    def openbao(self) -> OpenBaoClient:
        if self._openbao is None:
            self._openbao = OpenBaoClient(self.settings)
        return self._openbao

    def _cached(self, key: str, loader: Callable[[], T]) -> T:
        ttl = self.settings.secret_cache_ttl_seconds
        if ttl == 0:
            return loader()
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached and now < cached[0]:
                return cached[1]  # type: ignore[return-value]
        value = loader()
        with self._cache_lock:
            self._cache[key] = (now + ttl, value)
        return value

    def github_token(self) -> str:
        def load() -> str:
            if self.settings.github_token_source == "env":
                if not self.settings.github_token:
                    raise RuntimeError("GITHUB_TOKEN or GITHUB_TOKEN_FILE is required")
                return self.settings.github_token
            data = self.openbao.read_kv2_data(self.settings.openbao_github_path)
            value = data.get(self.settings.openbao_github_field)
            if not isinstance(value, str) or not value:
                raise RuntimeError(
                    f"OpenBao field '{self.settings.openbao_github_field}' must be a non-empty string"
                )
            return value

        return self._cached("github_token", load)

    def signing_material(self) -> tuple[str, str | None]:
        def load() -> tuple[str, str | None]:
            if self.settings.signing_key_source == "file":
                if not self.settings.signing_key_file:
                    raise RuntimeError("SIGNING_KEY_FILE is required")
                key = Path(self.settings.signing_key_file).read_text(encoding="utf-8")
                return key, None

            data = self.openbao.read_kv2_data(self.settings.openbao_signing_path)
            key = data.get(self.settings.openbao_signing_field)
            if not isinstance(key, str) or not key:
                raise RuntimeError(
                    f"OpenBao field '{self.settings.openbao_signing_field}' must be a non-empty string"
                )

            passphrase: str | None = None
            if self.settings.signing_format == "openpgp":
                candidate = data.get(self.settings.openbao_signing_passphrase_field)
                if candidate not in (None, ""):
                    if not isinstance(candidate, str):
                        raise RuntimeError(
                            f"OpenBao field '{self.settings.openbao_signing_passphrase_field}' must be a string"
                        )
                    passphrase = candidate
            return key, passphrase

        return self._cached("signing_material", load)
