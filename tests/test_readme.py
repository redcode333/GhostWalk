"""The README and docs are generated from templates and results.json: the templates may not contain typed numbers, every placeholder must resolve, and the committed files must be current."""
import pathlib, subprocess, sys
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import update_readme_numbers as U


def test_templates_contain_no_typed_numbers_and_every_placeholder_resolves():
    v = U.blocks()
    for name in U.TEMPLATES.values():
        tpl = (ROOT / "docs" / "templates" / name).read_text(encoding="utf8")
        assert U.audit(name, tpl) == []
        U.fill(tpl, v)                                                            # raises KeyError on an unknown placeholder


def test_the_audit_catches_a_typed_number():
    assert U.audit("t", "GhostWalk gets 76% top-1 on the held-out set.") != []
    assert U.audit("t", "AC@1 and p95 and 1-hop are structural, `409` and a [link](http://x/1) are not prose.") == []
    assert U.audit("t", "```\nthe code fence 123\n```\nprose without numbers") == []


def test_the_committed_readme_and_docs_are_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "update_readme_numbers.py"), "--check"], capture_output=True, text=True, encoding="utf8")
    assert r.returncode == 0, r.stdout + r.stderr


def test_copy_never_claims_to_beat_postgres_or_states_a_relative_gain(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("GhostWalk beats Postgres here.\nIt is 20% better than a vector store.\nA relative improvement of note.\nPostgres matches accuracy and is faster on raw path queries.\n", encoding="utf8")
    found = U.copy_check([bad])
    assert len(found) == 3 and not any("faster on raw" in f for f in found)
    assert U.copy_check(U.copy_files()) == []                              # the README, docs and UI copy are clean
