"""Unit tests for scripts/check-readme-claims.py's pure logic (regex
extraction + comparison). The script's filename has a hyphen, so it is loaded
by path via importlib rather than a normal package import; the module is
never executed as `__main__` here, so no subprocess/file I/O happens as a
side effect of import.

The subprocess-driven helpers (`_actual_test_count`, `_actual_coverage_pct`)
are deliberately not unit-tested here: they are thin I/O wrappers around
`pytest --collect-only` and `coverage report`, exercised for real every time
`make test` runs this script as its own gate step — the same convention the
repo already applies to its other doc/claim-checking scripts (e.g.
`scripts/writeup-check.py`), which run against the live repo rather than
synthetic fixtures.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path
from types import ModuleType

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "check-readme-claims.py"


def _load_check_readme_claims() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_readme_claims", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_readme_claims = _load_check_readme_claims()


def test_parse_claim_extracts_count_and_percentage() -> None:
    text = "strict typing, 433 tests at 97% coverage, dependency and secret scans"
    assert check_readme_claims.parse_claim(text) == (433, 97)


def test_parse_claim_is_none_when_wording_is_absent() -> None:
    assert check_readme_claims.parse_claim("no such claim in this text") is None


def test_parse_claim_ignores_unrelated_numbers() -> None:
    text = "v0.1.0 shipped on day 30; separately, 10 tests at 5% coverage, more text"
    assert check_readme_claims.parse_claim(text) == (10, 5)


def test_find_drift_is_empty_when_numbers_match() -> None:
    assert check_readme_claims.find_drift(433, 97, 433, 97) == []


def test_find_drift_reports_stale_test_count_only() -> None:
    problems = check_readme_claims.find_drift(433, 97, 493, 97)
    assert len(problems) == 1
    assert "433" in problems[0]
    assert "493" in problems[0]


def test_find_drift_reports_stale_coverage_percentage_only() -> None:
    problems = check_readme_claims.find_drift(433, 97, 433, 96)
    assert len(problems) == 1
    assert "97%" in problems[0]
    assert "96%" in problems[0]


def test_find_drift_reports_both_when_both_are_stale() -> None:
    problems = check_readme_claims.find_drift(433, 97, 500, 90)
    assert len(problems) == 2


def test_readme_currently_contains_a_well_formed_claim() -> None:
    # A narrow sanity check that the live README still matches the pattern
    # this script depends on — if this ever fails, the wording changed and
    # the CLAIM regex (or the README) needs a deliberate update, not a silent
    # gate no-op.
    readme_text = check_readme_claims.README.read_text(encoding="utf-8")
    assert check_readme_claims.parse_claim(readme_text) is not None


# --- The supported Python version, stated in eleven places ------------------
#
# ADR 0002 set the floor to >=3.10; ADR 0004 superseded it with >=3.12. The
# `requires-python` key moved and the CI matrix moved; the prose did not. On
# 2026-08-28 the Makefile's audit-waiver rationale still said "with the floor
# now >=3.10", `pyproject.toml`'s own comments said the same in two places and
# claimed "we type-check our own code against py310" twelve lines below
# `python_version = "3.12"`, and `docs/PROJECT-SCOPE.md` and
# `docs/DOCUMENTATION-AUDIT.md` both declared the package as ">=3.10".
#
# A repo whose whole pitch is "every claim is checkable" should not need a
# human to notice that. This derives the floor from `pyproject.toml` and holds
# the prose to it.

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Any doc sentence declaring the Python this package needs. Narrow on purpose:
#: a *historical* statement inside a dated record ("as of the 3.10 migration")
#: is not a claim about today, and rewriting those would falsify the record.
FLOOR_CLAIM = re.compile(
    r"for Python `?(>=\s*3\.\d+)`?|package `lavender-rotation` \(?(>=\s*3\.\d+)"
)

DOCS_STATING_A_FLOOR = ("docs/PROJECT-SCOPE.md", "docs/DOCUMENTATION-AUDIT.md")


def _declared_floor() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["requires-python"]).replace(" ", "")


def test_the_python_floor_is_declared_once_and_the_docs_match_it() -> None:
    floor = _declared_floor()
    assert floor.startswith(">="), floor
    for rel in DOCS_STATING_A_FLOOR:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        claims = {(m.group(1) or m.group(2)).replace(" ", "") for m in FLOOR_CLAIM.finditer(text)}
        assert claims, f"{rel} no longer states a Python floor; update this test or the doc"
        assert claims == {floor}, (
            f"{rel} declares Python {sorted(claims)} while pyproject.toml requires {floor}"
        )


def test_the_ruff_and_mypy_targets_match_the_declared_floor() -> None:
    """The two tool targets are the same decision written twice more."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    floor = _declared_floor().removeprefix(">=")
    major, minor = floor.split(".")[:2]
    assert data["tool"]["ruff"]["target-version"] == f"py{major}{minor}"
    assert data["tool"]["mypy"]["python_version"] == f"{major}.{minor}"


def test_the_ci_matrix_contains_no_runtime_below_the_floor() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    matrix = re.search(r"python-version:\s*\[(?P<versions>[^\]]+)\]", workflow)
    assert matrix is not None, "the CI matrix is no longer a plain literal list"
    versions = [v.strip().strip("\"'") for v in matrix.group("versions").split(",")]
    floor = tuple(int(part) for part in _declared_floor().removeprefix(">=").split("."))
    for version in versions:
        parsed = tuple(int(part) for part in version.split("."))
        assert parsed >= floor, (
            f"CI runs Python {version}, below the declared floor {_declared_floor()}"
        )
