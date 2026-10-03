# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from types import SimpleNamespace

from git_signing_mcp.secrets import SecretResolver


def _settings(**overrides):
    values = {
        "secret_cache_ttl_seconds": 300,
        "github_token_source": "openbao",
        "github_token": None,
        "openbao_github_path": "git-signing/github",
        "openbao_github_field": "token",
        "signing_key_source": "openbao",
        "signing_key_file": None,
        "signing_format": "openpgp",
        "openbao_signing_path": "git-signing/signing",
        "openbao_signing_field": "private_key",
        "openbao_signing_passphrase_field": "passphrase",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_signing_material_reads_openbao_once(monkeypatch):
    resolver = SecretResolver(_settings())
    calls = []

    class FakeOpenBao:
        def read_kv2_data(self, path):
            calls.append(path)
            return {"private_key": "key", "passphrase": "secret"}

    monkeypatch.setattr(resolver, "_openbao", FakeOpenBao())

    assert resolver.signing_material() == ("key", "secret")
    assert resolver.signing_material() == ("key", "secret")
    assert calls == ["git-signing/signing"]


def test_github_token_uses_ttl_cache(monkeypatch):
    resolver = SecretResolver(_settings())
    calls = []

    class FakeOpenBao:
        def read_kv2_data(self, path):
            calls.append(path)
            return {"token": "example-token"}

    monkeypatch.setattr(resolver, "_openbao", FakeOpenBao())

    assert resolver.github_token() == "example-token"
    assert resolver.github_token() == "example-token"
    assert calls == ["git-signing/github"]
