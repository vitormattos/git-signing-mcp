<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Contributing

Use pull requests for changes.

Run:

```bash
python -m pip install -e ".[dev]"
ruff check src tests scripts
pytest -q
docker build .
```

Every commit should carry a DCO trailer whose identity matches the commit author:

```text
Signed-off-by: Your Name <you@example.com>
```

When using local Git, git commit -s is the preferred way to add it.

Do not commit private keys, GitHub tokens, OpenBao AppRole credentials, .env
files, or production bearer tokens.

## CI helpers and local reproduction

CI YAML is deliberately orchestration-only. Exercise the Python commands and
security assertions without Docker/GitHub credentials:

```bash
pytest -q tests/test_workflow_helpers.py
ruff check src tests scripts
```

- `scripts/run_benchmark_matrix.py` owns the original/integrated revision
  matrix, checks the pinned baseline, and emits `BENCHMARK_JSON` reports.
  It requires three local checkouts (`harness`, `original`, `integrated`)
  when run with its defaults, and a disposable root:
  `python harness/scripts/run_benchmark_matrix.py --output-dir /tmp/bench-output`.
  Provide `--tmpfs-root` if `/dev/shm` is unavailable. It writes only to
  the supplied output directory and temporary fixture roots.
- `scripts/check_compose.py` invokes Docker Compose with temporary dummy
  secrets and checks network isolation, unpublished ports, and .dockerignore.
  It refuses to overwrite an existing credential. Set
  `OPENAI_TUNNEL_ID`, `GIT_IDENTITY_NAME` and `GIT_IDENTITY_EMAIL` as
  in `.github/workflows/compose.yml` for a standalone run.
- `scripts/smoke_image.py git-signing-mcp:test` verifies importability
  and unprivileged UID on an already-built image.

These helpers require no production GitHub or OpenBao tokens. The benchmark
compares disposable local Git operations, never a production push.
