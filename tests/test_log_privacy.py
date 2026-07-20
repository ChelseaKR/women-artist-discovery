"""No-identity-in-logs gate (OBS-11) — the no-inference invariant extends into
the log stream.

The diagnostic channel must never become an identity channel: log lines may
carry stage/timing/count/id data, never identity vocabulary or per-artist
identity values. Two legs, mirroring ``tests/test_no_inference.py``:

1. **Behavioural** — run the logging-heavy demo pipeline end to end with every
   ``wad.*`` record captured, format each record with *both* shipped formatters
   (kv and JSON), and assert no identity vocabulary appears anywhere in the
   stream.
2. **Structural** — an AST scan over every logging call site in ``pipeline``,
   ``recommender``, ``app``, and ``export`` proves no call passes an
   identity-bearing name, attribute, or literal.

If a future change legitimately needs to log an identity-*adjacent* aggregate
(say, a coverage count), it must be reviewed and the vocabulary below adjusted
deliberately in the same PR — that friction is the point of the gate.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

import app
import export
import pipeline
import recommender
from pipeline.cache import Cache
from pipeline.ingest import ingest
from pipeline.logconfig import JsonFormatter, KeyValueFormatter, configure_logging

#: Identity vocabulary that must never appear in the log stream. Word-boundary
#: matched, case-insensitive ("male" must not match "female" and vice versa —
#: both are listed explicitly).
IDENTITY_LOG_VOCABULARY = re.compile(
    r"\b("
    r"gender|pronoun|identity|identities|"
    r"woman|women|man|men|female|male|nonbinary|non-binary|"
    r"fronted|self-identified|band-composition|p21"
    r")\b",
    re.IGNORECASE,
)

#: Receivers that mark a call as a *logging* call (``st.info`` is a Streamlit
#: UI banner, not a log — deliberately excluded).
_LOGGER_NAMES = {"log", "logger", "_log", "_logger", "logging"}
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_demo_pipeline_log_stream_carries_no_identity_vocabulary(
    demo_user, source, enricher
) -> None:
    """Behavioural proof: a real cached ingest run logs no identity vocabulary.

    The demo world contains artists with sourced woman/nonbinary identities, so
    if any log call site leaked identity data this run would produce it.
    """
    root = configure_logging(level=logging.DEBUG)
    capture = _CaptureHandler()
    root.addHandler(capture)
    cache = Cache(":memory:")
    try:
        ingest(demo_user, source, enricher, cache=cache, fetched_at="2026-07-17")
    finally:
        cache.close()
        root.removeHandler(capture)
        configure_logging()  # restore INFO/kv defaults for the rest of the suite

    assert capture.records, "expected the ingest path to emit log records"
    for formatter in (KeyValueFormatter(), JsonFormatter()):
        for record in capture.records:
            line = formatter.format(record)
            match = IDENTITY_LOG_VOCABULARY.search(line)
            if match is not None:
                raise AssertionError(
                    f"identity vocabulary {match.group(0)!r} leaked into the log "
                    f"stream (OBS-11): {line!r}"
                )


def _core_files() -> list[Path]:
    roots = [
        Path(pipeline.__file__).parent,
        Path(recommender.__file__).parent,
        Path(app.__file__).parent,
        Path(export.__file__).parent,
    ]
    return [p for root in roots for p in root.rglob("*.py")]


def _is_logging_call(node: ast.Call) -> bool:
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in _LOG_METHODS):
        return False
    receiver = func.value
    if isinstance(receiver, ast.Name):
        return receiver.id.lower() in _LOGGER_NAMES
    if isinstance(receiver, ast.Attribute):  # e.g. ``self.log.info(...)``
        return receiver.attr.lower() in _LOGGER_NAMES
    if isinstance(receiver, ast.Call):  # e.g. ``logging.getLogger(...).info(...)``
        inner = receiver.func
        return isinstance(inner, ast.Attribute) and inner.attr == "getLogger"
    return False


def test_no_logging_call_site_passes_identity_data() -> None:
    """Structural proof: no log call in the core packages names identity.

    Scans the *source text of every logging call* (format strings, keyword
    names, passed attributes/variables alike) so a violation is caught at
    review time, before it ever runs.
    """
    violations: list[str] = []
    for path in _core_files():
        source_text = path.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_logging_call(node):
                segment = ast.get_source_segment(source_text, node) or ""
                match = IDENTITY_LOG_VOCABULARY.search(segment)
                if match:
                    violations.append(
                        f"{path.name}:{node.lineno} logs identity vocabulary "
                        f"{match.group(0)!r}: {segment!r}"
                    )
    assert not violations, "identity data must never enter the log stream (OBS-11):\n" + "\n".join(
        violations
    )


def test_gate_scans_a_nonempty_call_population() -> None:
    """The structural gate is not vacuous: it actually finds logging calls."""
    count = 0
    for path in _core_files():
        source_text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source_text)):
            if isinstance(node, ast.Call) and _is_logging_call(node):
                count += 1
    assert count >= 4, f"expected the core packages to contain logging calls, found {count}"
