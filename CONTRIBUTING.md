<!--
SPDX-FileCopyrightText: 2026 Vitor Mattos <1079143+vitormattos@users.noreply.github.com>
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
