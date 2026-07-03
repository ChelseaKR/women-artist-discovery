"""Root-level pytest bootstrap.

FIX-12: ``pipeline.cache`` resolves its ``DEFAULT_DB_PATH`` (via
``pipeline.paths.default_db_path()``) at import time. This root ``conftest.py``
is loaded before ``tests/conftest.py`` (and therefore before anything imports
``pipeline.cache``), so setting ``WAD_DATA_DIR`` here to an ephemeral,
per-session directory keeps the test suite from ever creating or touching the
real per-user data directory (``~/.local/share/wad``, ``~/Library/Application
Support/wad``, …) on the machine running the tests.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("WAD_DATA_DIR", tempfile.mkdtemp(prefix="wad-test-data-"))
