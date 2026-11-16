"""Scan local directories (CLI `gw map import ./acme`) or GitHub repos (the GitHub App) for dependency evidence."""
from __future__ import annotations
import pathlib
from .parsers import Finding, classify, parse_file, merge, summarize

MAX_FILE = 300_000
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "vendor", "target"}


def is_single_repo(root):
    """A folder with infra files at its own top level (a compose file, a Helm chart, manifests) is one repo, even if it has subfolders."""
    root = pathlib.Path(root)
    return any(p.is_file() and classify(p.name) for p in root.iterdir())


def repo_folders(root):
    """The repos under `root`: its immediate subdirectories, unless the root is itself one repo."""
    root = pathlib.Path(root)
    if is_single_repo(root):
        return []
    return [d for d in sorted(root.iterdir()) if d.is_dir() and d.name not in SKIP_DIRS]


def scan_directory(root, repos_are_subdirs=True):
    """Each immediate subdirectory is one repo when `repos_are_subdirs` and the root has no infra files of its own."""
    root = pathlib.Path(root)
    found = Finding()
    dirs = repo_folders(root) if repos_are_subdirs else []
    repos = [(d.name, d) for d in dirs] or [(root.name, root)]
    for name, base in repos:
        for p in sorted(base.rglob("*")):
            if not p.is_file() or any(part in SKIP_DIRS for part in p.relative_to(base).parts):
                continue
            rel = p.relative_to(base).as_posix()
            kind = classify(rel)
            if not kind or p.stat().st_size > MAX_FILE:
                continue
            parse_file(kind, p.read_text(encoding="utf8", errors="replace"), name, rel, found, owner=name)
    return found


def scan_texts(files):
    """files: iterable of (repo, path, text). Used by the GitHub scan and tests."""
    found = Finding()
    for repo, path, text in files:
        kind = classify(path)
        if kind:
            parse_file(kind, text, repo, path, found, owner=repo.split("/")[-1])
    return found


def proposals(found):
    edges = merge(found)
    return {"summary": summarize(found, edges), "services": [{"name": n, **v} for n, v in sorted(found.services.items())],
            "edges": [e.to_dict() | {"accepted": e.confidence != "low"} for e in edges]}
