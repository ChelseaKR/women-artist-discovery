"""Where WAD stores its local data (FIX-12 — operability: a documented, stable
data location instead of a cwd-relative ``data/`` folder).

Resolution order:

1. ``WAD_DATA_DIR`` env var, if set to a non-empty value — always honoured,
   any OS.
2. Otherwise a platformdirs-style per-OS user-data directory, computed with
   the standard library only (no new dependency): ``~/Library/Application
   Support/wad`` on macOS, ``%APPDATA%\\wad`` on Windows, and
   ``$XDG_DATA_HOME/wad`` (default ``~/.local/share/wad``) elsewhere.

Both paths are absolute and independent of the process's current working
directory, so two shells started in different directories resolve to the
same cache (the bug this module fixes: ``pipeline/cache.py`` used to default
to the cwd-relative ``data/cache.db``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ENV_VAR = "WAD_DATA_DIR"
_APP_NAME = "wad"
_DB_FILENAME = "cache.db"


def resolve_data_dir() -> Path:
    """Return the absolute directory WAD stores its local data in.

    Honours ``WAD_DATA_DIR`` when set to a non-empty (whitespace-stripped)
    value; otherwise falls back to :func:`_default_data_dir`. Pure path
    resolution — does not touch the filesystem.
    """
    override = os.environ.get(_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _default_data_dir()


def _default_data_dir() -> Path:
    """The platformdirs-style default, keyed off ``sys.platform``."""
    if sys.platform == "darwin":
        base = Path(os.path.expanduser("~/Library/Application Support"))
    elif sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path(os.path.expanduser("~/AppData/Roaming"))
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path(os.path.expanduser("~/.local/share"))
    return (base / _APP_NAME).resolve()


def default_db_path() -> Path:
    """Return the resolved cache database path, creating its parent directory.

    Callers that only need the *path* (e.g. display in ``wad doctor``) can use
    :func:`resolve_data_dir` instead to avoid the filesystem write.
    """
    data_dir = resolve_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / _DB_FILENAME
