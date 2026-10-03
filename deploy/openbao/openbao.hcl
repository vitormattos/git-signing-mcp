# SPDX-FileCopyrightText: 2026 Vitor Mattos <1079143+vitormattos@users.noreply.github.com>
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
