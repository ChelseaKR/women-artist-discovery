"""The CLI's ``--json`` documents, and the guarantees their shape is supposed to carry.

Three things are worth testing here and one thing is not. Not worth testing: that
a document has keys. Worth testing:

* **The no-inference guarantee is structural.** A pick whose identity basis is
  ``unknown`` must carry no provenance and a ``sourced_gender`` of ``"unknown"``,
  and a pick with a sourced gender must carry provenance. That is the property a
  reviewer runs ``recommend --json | jq`` to check, so it is checked here over
  generated inputs rather than one fixture.
* **The schemas describe the documents.** Committed bytes are regenerated and
  compared, real command output is validated against them, and the validator's
  own keyword coverage is asserted -- otherwise a checker could pass a document
  by quietly ignoring the one constraint that mattered.
* **`recommend --json` is byte-stable.** Across *separate interpreters* with
  different ``PYTHONHASHSEED`` values, and over a world with enough picks that
  order is observable. Two renders inside one interpreter would prove nothing:
  set iteration over strings is stable there, so a dropped sort is invisible.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pipeline import jsonout
from pipeline.cli import main
from pipeline.doctor import NETWORK_EGRESS_MODULES

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"


def run_json(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, Any]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, json.loads(captured.out)


def schema(name: str) -> dict[str, Any]:
    return dict(json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8")))


def assert_valid(document: Any, name: str) -> None:
    errors = jsonout.validate(document, schema(name))
    assert errors == [], errors


# --- the schemas describe the documents --------------------------------------


def test_committed_schemas_match_the_definitions() -> None:
    for name in sorted(jsonout.SCHEMAS):
        committed = (SCHEMA_DIR / name).read_text(encoding="utf-8")
        assert committed == jsonout.render_schema(name), (
            f"{name} is stale; run `python3 scripts/gen_schemas.py` and commit the result"
        )


def test_the_validator_understands_every_keyword_the_schemas_use() -> None:
    """A checker that ignores a keyword passes documents it should refuse."""
    for name in sorted(jsonout.SCHEMAS):
        used = jsonout.schema_keywords(jsonout.SCHEMAS[name]())
        unsupported = sorted(used - jsonout.SUPPORTED_KEYWORDS)
        assert unsupported == [], f"{name} uses {unsupported}"


def test_every_document_has_its_own_schema_version() -> None:
    """One shared number would tell every consumer their contract had changed
    when only one document moved."""
    assert set(jsonout.SCHEMA_VERSIONS) == {"recommend", "export", "doctor", "error"}


def test_recommend_output_validates(capsys: pytest.CaptureFixture[str]) -> None:
    code, document = run_json(capsys, ["recommend", "--json", "--k", "5"])
    assert code == 0
    assert_valid(document, "recommend")


def test_export_output_validates(capsys: pytest.CaptureFixture[str]) -> None:
    code, document = run_json(capsys, ["export", "--json", "--k", "3", "--format", "csv"])
    assert code == 0
    assert_valid(document, "export")


def test_doctor_output_validates(capsys: pytest.CaptureFixture[str]) -> None:
    code, document = run_json(capsys, ["doctor", "--json"])
    assert code in (0, 1)
    assert_valid(document, "doctor")


def test_a_refusal_validates_and_exits_non_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code, document = run_json(
        capsys, ["recommend", "--json", "--year-from", "2010", "--year-to", "2000"]
    )
    assert code == 2
    assert document["ok"] is False
    assert document["error"]["kind"] == "invalid_filter"
    assert_valid(document, "error")


def test_a_live_mode_refusal_is_json_too(capsys: pytest.CaptureFixture[str]) -> None:
    code, document = run_json(capsys, ["recommend", "--json", "--user", "nobody-cached-here"])
    assert code == 2
    assert document["error"]["kind"] == "live_mode"
    assert_valid(document, "error")


def test_the_validator_rejects_what_the_schema_forbids() -> None:
    """The suite must be able to tell a valid document from an invalid one."""
    document = jsonout.error_document(command="recommend", kind="live_mode", message="x")
    assert jsonout.validate(document, schema("error")) == []
    broken = {**document, "extra": 1}
    assert jsonout.validate(broken, schema("error")) != []
    wrong_version = {**document, "schema_version": 99}
    assert jsonout.validate(wrong_version, schema("error")) != []
    empty_message = {**document, "error": {"kind": "live_mode", "message": ""}}
    assert jsonout.validate(empty_message, schema("error")) != []


def test_an_unknown_error_kind_is_refused_at_construction() -> None:
    with pytest.raises(ValueError):
        jsonout.error_document(command="recommend", kind="vibes", message="x")


def test_render_schema_refuses_an_unknown_name() -> None:
    with pytest.raises(KeyError):
        jsonout.render_schema("nope.schema.json")


def test_a_schema_using_an_unknown_keyword_raises_rather_than_passing() -> None:
    with pytest.raises(ValueError):
        jsonout.validate({}, {"type": "object", "multipleOf": 3})


def test_a_schema_declaring_an_unknown_type_raises() -> None:
    with pytest.raises(ValueError):
        jsonout.validate("x", {"type": "duration"})


# --- the guarantee the document exists to make checkable ----------------------


def _identity_violations(document: dict[str, Any]) -> list[str]:
    """Every way this run's picks break the sourced-or-unknown rule."""
    problems: list[str] = []
    for pick in document["recommendations"]:
        identity = pick["identity"]
        sources = identity["provenance"] + identity["queer_provenance"]
        if identity["inferred"] is not False:
            problems.append(f"{pick['artist_id']}: inferred is not false")
        if identity["basis"] == "unknown":
            if identity["sourced_gender"] != "unknown":
                problems.append(f"{pick['artist_id']}: unknown basis with a sourced gender")
            if sources:
                problems.append(f"{pick['artist_id']}: unknown basis carrying provenance")
        if identity["sourced_gender"] != "unknown" and not identity["provenance"]:
            problems.append(f"{pick['artist_id']}: a gender label with no citation")
    return problems


@settings(deadline=None, max_examples=25)
@given(
    k=st.integers(min_value=1, max_value=12),
    lens=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    explore=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    lens_name=st.sampled_from(["women-nonbinary", "queer"]),
    hide_men=st.booleans(),
)
def test_no_pick_ever_carries_an_unsourced_identity_label(
    k: int, lens: float, explore: float, lens_name: str, hide_men: bool
) -> None:
    """The property `recommend --json | jq` is supposed to let a reviewer check.

    Run over the library rather than the CLI so hypothesis can drive it: the
    document builder is the thing under test, and the CLI is glue over it.
    """
    from pipeline.cache import DEFAULT_DB_PATH, Cache
    from pipeline.demo import demo_catalog, demo_profile, demo_source
    from recommender.coverage import identity_coverage
    from recommender.hybrid import recommend
    from recommender.lens import LENSES

    profile, catalog, source = demo_profile(), demo_catalog(), demo_source()
    with Cache(DEFAULT_DB_PATH) as cache:
        feedbacks = cache.load_feedback(profile.username)
    recs = recommend(
        profile,
        catalog,
        source,
        k=k,
        lens_strength=lens,
        explore=explore,
        feedbacks=feedbacks,
        hide_sourced_men=hide_men,
        lens=LENSES[lens_name],
    )
    document = jsonout.recommend_document(
        recommendations=recs,
        coverage=identity_coverage(recs),
        listener=profile.username,
        lens_name=lens_name,
        lens_strength=lens,
        explore=explore,
        hide_sourced_men=hide_men,
        k=k,
        content_filter_description="filters: none",
    )
    assert _identity_violations(document) == []
    assert jsonout.validate(document, schema("recommend")) == []


def test_the_violation_detector_can_actually_see_a_violation() -> None:
    """The property above is only worth something if its checker fires.

    A guard that cannot detect the defect it guards against reads as a pass on
    every run, so the checker gets a negative control of its own.
    """
    document: dict[str, Any] = {
        "recommendations": [
            {
                "artist_id": "made-up",
                "identity": {
                    "basis": "unknown",
                    "sourced_gender": "woman",
                    "inferred": False,
                    "provenance": [],
                    "queer_provenance": [],
                },
            }
        ]
    }
    assert _identity_violations(document) != []


def test_an_empty_run_reports_no_share_rather_than_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A zero share would read as a measurement. There is none over no picks."""
    code, document = run_json(
        capsys,
        ["recommend", "--json", "--include-tags", "no-artist-carries-this-tag"],
    )
    assert code == 0
    assert document["recommendations"] == []
    assert document["identity_coverage"]["total"] == 0
    assert document["identity_coverage"]["sourced_share"] is None
    assert document["identity_coverage"]["unknown_share"] is None
    assert_valid(document, "recommend")


# --- doctor publishes what the tool may contact -------------------------------


def test_doctor_json_publishes_the_egress_allowlist(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _code, document = run_json(capsys, ["doctor", "--json"])
    assert set(document["egress_allowlist"]["modules"]) == set(NETWORK_EGRESS_MODULES)
    assert document["egress_allowlist"]["hosts"]
    assert all(host.startswith("https://") for host in document["egress_allowlist"]["hosts"])


def test_doctor_json_says_whether_upstream_was_probed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --check-upstream there are no upstream checks at all, and their
    absence is not a report that every API was reachable."""
    _code, document = run_json(capsys, ["doctor", "--json"])
    assert document["upstream_checked"] is False
    assert not [c for c in document["checks"] if c["name"].startswith("upstream:")]


# --- byte stability -----------------------------------------------------------

_STABILITY_SCRIPT = (
    "import sys; from pipeline.cli import main; "
    "sys.exit(main(['recommend', '--json', '--k', '12', '--explore', '0.7']))"
)


def _render_under(seed: str) -> str:
    environment = {**os.environ, "PYTHONHASHSEED": seed}
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _STABILITY_SCRIPT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=environment,
    )
    return completed.stdout


def test_recommend_json_is_byte_identical_across_interpreters() -> None:
    """Across processes, with the hash seed varied, over a world of twelve picks.

    Every clause is load-bearing. Two renders inside one interpreter share a
    stable set iteration order, so a dropped `sorted()` is invisible to them.
    And a fixture with one row has no order to get wrong: `--k 12` and a
    non-zero `--explore` are what make ordering observable at all.
    """
    renders = [_render_under(seed) for seed in ("0", "1", "12345")]
    assert renders[0] == renders[1] == renders[2]
    # And it is a real document, not three identical error pages.
    document = json.loads(renders[0])
    assert document["command"] == "recommend"
    # The demo world yields seven picks here. Asserted so that a future change
    # shrinking it cannot quietly make this a one-row fixture, where there is no
    # order left to get wrong and the guard would pass on anything.
    assert len(document["recommendations"]) >= 5
    assert_valid(document, "recommend")
