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
