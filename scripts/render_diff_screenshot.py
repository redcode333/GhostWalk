"""Render the `gw diff` output on the test fixture to docs/gw-diff.svg (then PNG with a headless browser): python scripts/render_diff_screenshot.py"""
import io, pathlib, sys, tempfile, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tests"))
from rich.console import Console
from typer.testing import CliRunner
import ghostwalk.cli as cli
import test_diff as T

out = pathlib.Path(__file__).resolve().parent.parent / "docs"
out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    repo = tmp / "acme"
    repo.mkdir()
    T.git(repo, "init", "-q", "-b", "main")
    (repo / "docker-compose.yml").write_text(T.C1)
    T.git(repo, "add", "."); T.git(repo, "commit", "-qm", "base")
    T.git(repo, "checkout", "-qb", "feature")
    (repo / "docker-compose.yml").write_text(T.C2)
    T.git(repo, "commit", "-qam", "add config-svc dependency")
    g = tmp / "graph.json"
    g.write_text(json.dumps(T.GRAPH))
    cli.console = Console(record=True, force_terminal=True, width=104, highlight=False, file=io.StringIO())
    r = CliRunner().invoke(cli.app, ["diff", "--repo", str(repo), "--base", "main", "--head", "feature", "--graph", str(g)])
    assert r.exit_code == 0, r.output
    cli.console.save_svg(str(out / "gw-diff.svg"), title="gw diff")
print("wrote", out / "gw-diff.svg")
