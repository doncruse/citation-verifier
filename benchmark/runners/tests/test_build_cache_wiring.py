"""Smoke test for the build-side gold-DB cache integration in build_dataset.py.

We don't run build_dataset.py end-to-end here (it does real CL mining).
Instead we verify that the cache-lookup logic is present and uses the
cases table correctly when given a populated GoldDB.
"""
from pathlib import Path
from citation_verifier.gold_db import GoldDB


def test_cases_table_supports_cite_string_lookup(tmp_path: Path):
    """The build-side cache logic queries `cases.cite_string`. Verify
    a known cite_string returns a cluster_id."""
    db = GoldDB(tmp_path / "gold.db")
    db.upsert_case(
        cluster_id=12345,
        canonical_name="Foo v. Bar",
        court_id="ca9",
        year=2010,
        cite_string="100 F.3d 1",
        run_id="t",
    )
    cur = db.conn.execute(
        "SELECT cluster_id, canonical_name FROM cases WHERE cite_string = ?",
        ("100 F.3d 1",),
    ).fetchone()
    assert cur is not None
    assert cur["cluster_id"] == 12345
    assert cur["canonical_name"] == "Foo v. Bar"

    # Cache miss case
    miss = db.conn.execute(
        "SELECT * FROM cases WHERE cite_string = ?",
        ("999 U.S. 999",),
    ).fetchone()
    assert miss is None


def test_build_dataset_imports_goldDB():
    """build_dataset.py should import GoldDB so the cache wiring is in place."""
    p = Path(__file__).parent.parent / "build_dataset.py"
    src = p.read_text(encoding="utf-8")
    assert (
        "from citation_verifier.gold_db import GoldDB" in src
        or "import citation_verifier.gold_db" in src
    ), "build_dataset.py must import GoldDB for build-side cache"
    assert "cite_string" in src, (
        "build_dataset.py must reference cite_string to do cache lookups"
    )
