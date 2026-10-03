# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

ui = false
api_addr = "http://openbao:8200"

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

storage "pebbledb" {
  path = "/openbao/file/pebbledb"
}

# This deployment deliberately treats the trusted VPS/root account as the local
# source of trust for auto-unseal. Keep this key outside the OpenBao data volume
# and never back up the key together with the encrypted OpenBao storage.
seal "static" {
  current_key_id = "git-signing-mcp-static-v1"
  current_key    = "file:///run/secrets/openbao_static_seal_key"
}
