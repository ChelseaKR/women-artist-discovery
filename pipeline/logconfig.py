"""Structured, local-only logging (FIX-12 — operability pass).

Every WAD log record is written to **stderr only**, in a flat ``key=value``
line. This is a deliberate privacy invariant, not an incidental choice: the
same no-egress posture FIX-07's runtime guard enforces for API calls applies
to logging too, so a diagnostic channel can never become a telemetry channel.
There is no ``logging.handlers.HTTPHandler``, ``SysLogHandler`` pointed at a
remote host, queue handler, or any other network sink configured anywhere in
this module — only a single :class:`logging.StreamHandler` on ``sys.stderr``.

Module loggers live under the ``wad`` namespace (``wad.ingest``, ``wad.cli``,
…) so a single handler on the ``wad`` root logger captures everything and
callers can filter/silence a subsystem with the normal ``logging`` API.
"""

from __future__ import annotations

import logging
import sys
import time

_NAMESPACE = "wad"
_CONFIGURED_LOGGERS: set[int] = set()


class KeyValueFormatter(logging.Formatter):
    """Compact ``key=value`` line formatter — local-only, no external sink."""

    converter = staticmethod(time.gmtime)  # UTC, deterministic across machines

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        timestamp = self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ")
        parts = [
            f"ts={timestamp}",
            f"level={record.levelname.lower()}",
            f"logger={record.name}",
            f"msg={record.message!r}",
        ]
        if record.exc_info:
            parts.append(f"exc_info={self.formatException(record.exc_info)!r}")
        return " ".join(parts)


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the ``wad`` logger tree: one stderr handler, local-only.

    Idempotent per logger object — calling this more than once (``main()``
    plus a test, say) never duplicates handlers on the same logger.
    """
    root = logging.getLogger(_NAMESPACE)
    root.setLevel(level)
    if id(root) not in _CONFIGURED_LOGGERS:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(KeyValueFormatter())
        root.addHandler(handler)
        root.propagate = False
        _CONFIGURED_LOGGERS.add(id(root))
    return root


def get_logger(name: str) -> logging.Logger:
    """Return a module logger under the ``wad`` namespace, e.g. ``wad.ingest``."""
    return logging.getLogger(name)
