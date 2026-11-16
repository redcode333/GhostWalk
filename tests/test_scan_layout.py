"""A folder with infra files at its top level is one repo, even when it also has subfolders (alerts/, postmortems/); a folder of repos is still read repo by repo."""
import pathlib
from ghostwalk.discover.scan import repo_folders, scan_directory


def test_a_single_repo_with_subfolders_is_scanned_as_one(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services:\n  web:\n    image: x\n    depends_on: [api]\n  api:\n    image: y\n", encoding="utf8")
    (tmp_path / "alerts").mkdir(); (tmp_path / "alerts" / "a.json").write_text("{}", encoding="utf8")
    assert repo_folders(tmp_path) == []
    found = scan_directory(tmp_path)
    assert {"web", "api"} <= set(found.services)


def test_a_folder_of_repos_is_still_read_repo_by_repo(tmp_path):
    for name in ("checkout", "payments"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "docker-compose.yml").write_text(f"services:\n  {name}-api:\n    image: x\n", encoding="utf8")
    assert sorted(p.name for p in repo_folders(tmp_path)) == ["checkout", "payments"]
    assert {"checkout-api", "payments-api"} <= set(scan_directory(tmp_path).services)
