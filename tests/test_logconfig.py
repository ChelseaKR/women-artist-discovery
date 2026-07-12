"""FIX-12: structured, local-only logging."""

from __future__ import annotations

import logging
import sys

from pipeline.logconfig import KeyValueFormatter, configure_logging, get_logger


def _our_handlers(logger: logging.Logger) -> list[logging.Handler]:
    """Handlers configure_logging() itself attached (ignores pytest's own caplog
    handlers, which pytest attaches to any non-propagating logger like ``wad``)."""
    return [h for h in logger.handlers if isinstance(h.formatter, KeyValueFormatter)]


def test_configure_logging_attaches_one_stderr_handler() -> None:
    root = configure_logging()
    assert root.name == "wad"
    ours = _our_handlers(root)
    assert len(ours) == 1
    handler = ours[0]
    assert isinstance(handler, logging.StreamHandler)
    assert not isinstance(handler, logging.FileHandler)  # stderr, not a file on disk
    # Bound to *a* stderr-like stream — not asserting identity with the current
    # sys.stderr, since pytest's own output capturing swaps that object out
    # from under a handler created once and reused across the whole session.
    assert hasattr(handler.stream, "write")


def test_configure_logging_is_idempotent() -> None:
    first = configure_logging()
    second = configure_logging()
    assert second is first
    assert len(_our_handlers(second)) == 1  # no duplicate handler added on a second call


def test_get_logger_is_under_the_wad_namespace() -> None:
    log = get_logger("wad.ingest")
    assert log.name == "wad.ingest"
    assert log.parent is not None
    assert log.parent.name == "wad"


def test_formatter_renders_key_value_pairs() -> None:
    formatter = KeyValueFormatter()
    record = logging.LogRecord(
        name="wad.ingest",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="stage=%s event=%s",
        args=("fetch", "start"),
        exc_info=None,
    )
    line = formatter.format(record)
    assert "level=info" in line
    assert "logger=wad.ingest" in line
    assert "msg='stage=fetch event=start'" in line


def test_formatter_includes_exception_info() -> None:
    formatter = KeyValueFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="wad.ingest",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="something failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    line = formatter.format(record)
    assert "exc_info=" in line
    assert "ValueError" in line
    assert "boom" in line


def test_no_network_handlers_are_ever_configured() -> None:
    root = configure_logging()
    for handler in root.handlers:
        assert isinstance(handler, logging.StreamHandler)
        assert not hasattr(handler, "host")  # rules out HTTPHandler / SysLogHandler-style sinks
