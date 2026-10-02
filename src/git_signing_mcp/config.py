from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _read_value(name: str, default: str | None = None) -> str | None:
    file_value = os.getenv(f"{name}_FILE")
    if file_value:
        return Path(file_value).read_text(encoding="utf-8").strip()
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    value = os.getenv(name, default)
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    tunnel_shared_secret: str
    allowed_repositories: tuple[str, ...]
    protected_branch_patterns: tuple[str, ...]
    allow_protected_branch_writes: bool
    max_writes_per_minute: int
    max_concurrent_writes: int
    max_file_bytes: int
    max_changes: int
    git_identity_name: str
    git_identity_email: str
    signing_format: str
    signing_key_source: str
    signing_key_file: str | None
    github_token_source: str
    github_token: str | None
    github_api_url: str
    openbao_addr: str | None
    openbao_namespace: str | None
    openbao_role_id: str | None
    openbao_secret_id: str | None
    openbao_auth_mount: str
    openbao_kv_mount: str
    openbao_signing_path: str
    openbao_signing_field: str
    openbao_signing_passphrase_field: str
    openbao_github_path: str
    openbao_github_field: str
    verify_retries: int

    @classmethod
    def from_env(cls) -> Settings:
        settings = cls(
            host=os.getenv("MCP_HOST", "0.0.0.0"),
            port=_int("MCP_PORT", 8080),
            allowed_hosts=_csv("MCP_ALLOWED_HOSTS", "mcp,mcp:*"),
            allowed_origins=_csv("MCP_ALLOWED_ORIGINS"),
            tunnel_shared_secret=_read_value("MCP_TUNNEL_SHARED_SECRET", "") or "",
            allowed_repositories=_csv("ALLOWED_REPOSITORIES", "*/*"),
            protected_branch_patterns=_csv(
                "PROTECTED_BRANCH_PATTERNS",
                "main,master,trunk,production,release/*",
            ),
            allow_protected_branch_writes=_bool(
                "ALLOW_PROTECTED_BRANCH_WRITES",
                False,
            ),
            max_writes_per_minute=_int("MAX_WRITES_PER_MINUTE", 10),
            max_concurrent_writes=_int("MAX_CONCURRENT_WRITES", 1),
            max_file_bytes=_int("MAX_FILE_BYTES", 1_048_576),
            max_changes=_int("MAX_CHANGES", 100),
            git_identity_name=_read_value("GIT_IDENTITY_NAME", "") or "",
            git_identity_email=_read_value("GIT_IDENTITY_EMAIL", "") or "",
            signing_format=os.getenv("SIGNING_FORMAT", "ssh"),
            signing_key_source=os.getenv("SIGNING_KEY_SOURCE", "file"),
            signing_key_file=_read_value("SIGNING_KEY_FILE"),
            github_token_source=os.getenv("GITHUB_TOKEN_SOURCE", "env"),
            github_token=_read_value("GITHUB_TOKEN"),
            github_api_url=os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/"),
            openbao_addr=_read_value("OPENBAO_ADDR"),
            openbao_namespace=_read_value("OPENBAO_NAMESPACE"),
            openbao_role_id=_read_value("OPENBAO_ROLE_ID"),
            openbao_secret_id=_read_value("OPENBAO_SECRET_ID"),
            openbao_auth_mount=os.getenv("OPENBAO_AUTH_MOUNT", "approle"),
            openbao_kv_mount=os.getenv("OPENBAO_KV_MOUNT", "secret"),
            openbao_signing_path=os.getenv("OPENBAO_SIGNING_PATH", "git-signing/signing"),
            openbao_signing_field=os.getenv("OPENBAO_SIGNING_FIELD", "private_key"),
            openbao_signing_passphrase_field=os.getenv(
                "OPENBAO_SIGNING_PASSPHRASE_FIELD", "passphrase"
            ),
            openbao_github_path=os.getenv("OPENBAO_GITHUB_PATH", "git-signing/github"),
            openbao_github_field=os.getenv("OPENBAO_GITHUB_FIELD", "token"),
            verify_retries=_int("VERIFY_RETRIES", 6),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.tunnel_shared_secret or len(self.tunnel_shared_secret) < 32:
            raise RuntimeError(
                "MCP_TUNNEL_SHARED_SECRET is required and must contain at least 32 characters"
            )
        if not self.git_identity_name or not self.git_identity_email:
            raise RuntimeError("GIT_IDENTITY_NAME and GIT_IDENTITY_EMAIL are required")
        if not self.allowed_repositories:
            raise RuntimeError("ALLOWED_REPOSITORIES must contain at least one repository pattern")
        if self.signing_format not in {"ssh", "openpgp"}:
            raise RuntimeError("SIGNING_FORMAT must be 'ssh' or 'openpgp'")
        if self.signing_key_source not in {"file", "openbao"}:
            raise RuntimeError("SIGNING_KEY_SOURCE must be 'file' or 'openbao'")
        if self.github_token_source not in {"env", "openbao"}:
            raise RuntimeError("GITHUB_TOKEN_SOURCE must be 'env' or 'openbao'")
        if self.max_changes < 1 or self.max_changes > 1000:
            raise RuntimeError("MAX_CHANGES must be between 1 and 1000")
        if self.max_writes_per_minute < 1 or self.max_writes_per_minute > 600:
            raise RuntimeError("MAX_WRITES_PER_MINUTE must be between 1 and 600")
        if self.max_concurrent_writes < 1 or self.max_concurrent_writes > 16:
            raise RuntimeError("MAX_CONCURRENT_WRITES must be between 1 and 16")
