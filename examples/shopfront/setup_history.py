"""Creates a git history for the shopfront example in a target folder, so `gw diff` has two refs to compare.

    python setup_history.py <target-folder>

main: the compose project as it is here.
declare-flags: one more commit, in which cart-api and inventory-api declare the feature-flags dependency (the change `gw diff` analyses).
"""
import pathlib, shutil, stat, subprocess, sys

SRC = pathlib.Path(__file__).resolve().parent
dst = pathlib.Path(sys.argv[1]).resolve()


def _force(func, path, _):
    import os
    os.chmod(path, stat.S_IWRITE)
    func(path)


if dst.exists():
    shutil.rmtree(dst, onerror=_force)
dst.mkdir(parents=True)


def git(*a):
    return subprocess.run(["git", *a], cwd=dst, check=True, capture_output=True, text=True)


for f in ("docker-compose.yml", "README.md"):
    shutil.copyfile(SRC / f, dst / f)
shutil.copytree(SRC / "alerts", dst / "alerts")
shutil.copytree(SRC / "postmortems", dst / "postmortems")
git("init", "-q", "-b", "main")
git("config", "user.name", "shopfront example")
git("config", "user.email", "example@ghostwalk.invalid")
git("add", "-A")
git("commit", "-q", "-m", "shopfront: services and their declared dependencies")
git("checkout", "-q", "-b", "declare-flags")
text = (dst / "docker-compose.yml").read_text(encoding="utf8")
changed = text.replace("    depends_on: [redis-cart]\n", "    depends_on: [redis-cart, feature-flags]\n")
changed = changed.replace("    image: shopfront/inventory\n    depends_on: [postgres-catalog]\n", "    image: shopfront/inventory\n    depends_on: [postgres-catalog, feature-flags]\n")
assert changed != text, "the change did not apply"
(dst / "docker-compose.yml").write_text(changed, encoding="utf8")
git("add", "-A")
git("commit", "-q", "-m", "cart-api and inventory-api read the feature flags")
git("checkout", "-q", "main")
print(f"history ready in {dst}: branches main and declare-flags")
