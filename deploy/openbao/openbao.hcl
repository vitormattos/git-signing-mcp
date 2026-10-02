ui = false
disable_mlock = false
api_addr = "http://openbao:8200"

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

storage "pebbledb" {
  path = "/openbao/file/pebbledb"
}
