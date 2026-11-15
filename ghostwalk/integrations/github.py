"""GitHub App client. The App is READ-ONLY: repository contents + issues (metadata is implicit).

  app JWT (RS256, 9 min)  ->  installation access token  ->  tree + file contents  (read)
  `issues` webhook        ->  verify_signature()           ->  postmortem proposals (see issues.py)

The App can't open pull requests (that needs write access), so the postmortem-template PR goes through
`open_template_pr()` with a separate, optional token (GITHUB_PR_TOKEN) the user controls; without it the UI shows a
prefilled "new file" link and a `gh` command instead.
"""
from __future__ import annotations
import base64, hashlib, hmac, os, time
from urllib.parse import quote
import httpx
from ..discover.parsers import classify

API = "https://api.github.com"
TEMPLATE_PATH = ".github/ISSUE_TEMPLATE/postmortem.yml"
MAX_FILES_PER_REPO = 120

POSTMORTEM_TEMPLATE = """\
name: Postmortem
description: Teach GhostWalk what really happened. Three fields; you review every proposed graph change before it applies.
title: "INC-: "
labels: ["postmortem"]
body:
  - type: input
    id: root_cause
    attributes:
      label: Actual root cause
      description: The service that really broke. Names or aliases both work.
      placeholder: config-svc
    validations:
      required: true
  - type: textarea
    id: path
    attributes:
      label: How it reached the alerting service
      description: "Service names or aliases, root first, one arrow between each. Unknown names are matched for you."
      placeholder: config-svc -> fraud-check -> payments -> checkout-api
    validations:
      required: true
  - type: textarea
    id: map_missed
    attributes:
      label: What the map got wrong (optional)
      description: A dependency that is not in the service catalog, or a name the monitoring uses for a service.
      placeholder: fraud-check reads feature flags from config-svc on every request. "cfg" is config-svc.
    validations:
      required: false
"""


class GitHubError(RuntimeError):
    pass


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """X-Hub-Signature-256 check (constant time). An unset secret fails closed."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    want = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header)


def app_jwt(app_id: str, private_key_pem: str, now: float | None = None) -> str:
    import jwt
    now = int(now or time.time())
    return jwt.encode({"iat": now - 30, "exp": now + 9 * 60, "iss": str(app_id)}, private_key_pem, algorithm="RS256")


class GitHub:
    def __init__(self, token: str | None = None, transport: httpx.BaseTransport | None = None):
        self.token = token
        self.http = httpx.Client(base_url=API, transport=transport, timeout=20,
                                 headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def get(self, path, **params):
        r = self.http.get(path, headers=self._h(), params=params)
        if r.status_code >= 400:
            raise GitHubError(f"GET {path}: {r.status_code} {r.text[:200]}")
        return r.json()

    @classmethod
    def from_app(cls, app_id, private_key_pem, installation_id, transport=None):
        boot = cls(app_jwt(app_id, private_key_pem), transport)
        r = boot.http.post(f"/app/installations/{installation_id}/access_tokens", headers=boot._h())
        if r.status_code >= 400:
            raise GitHubError(f"installation token: {r.status_code} {r.text[:200]}")
        return cls(r.json()["token"], transport)

    # ---- read-only scan --------------------------------------------------------------------
    def installation_repos(self):
        return [r["full_name"] for r in self.get("/installation/repositories", per_page=100).get("repositories", [])]

    def repo_files(self, full_name):
        """(repo, path, text) for every infra file in the repo's default branch."""
        tree = self.get(f"/repos/{full_name}/git/trees/HEAD", recursive="1")
        paths = [t["path"] for t in tree.get("tree", []) if t["type"] == "blob" and t.get("size", 0) < 300_000 and classify(t["path"])]
        out = []
        for path in paths[:MAX_FILES_PER_REPO]:
            c = self.get(f"/repos/{full_name}/contents/{quote(path)}")
            if c.get("encoding") == "base64":
                out.append((full_name, path, base64.b64decode(c["content"]).decode("utf8", "replace")))
        return out

    def scan(self, repos=None):
        files = []
        for repo in repos or self.installation_repos():
            files += self.repo_files(repo)
        return files

    # ---- the postmortem template PR (needs a write-capable token, NOT the read-only App) -------
    def open_template_pr(self, full_name, branch="ghostwalk/postmortem-template"):
        repo = self.get(f"/repos/{full_name}")
        base = repo["default_branch"]
        sha = self.get(f"/repos/{full_name}/git/ref/heads/{base}")["object"]["sha"]
        h = self._h()
        r = self.http.post(f"/repos/{full_name}/git/refs", headers=h, json={"ref": f"refs/heads/{branch}", "sha": sha})
        if r.status_code not in (201, 422):               # 422 = branch already exists; reuse it
            raise GitHubError(f"create branch: {r.status_code} {r.text[:200]}")
        body = {"message": "Add GhostWalk postmortem issue form", "branch": branch,
                "content": base64.b64encode(POSTMORTEM_TEMPLATE.encode()).decode()}
        existing = self.http.get(f"/repos/{full_name}/contents/{TEMPLATE_PATH}", headers=h, params={"ref": branch})
        if existing.status_code == 200:
            body["sha"] = existing.json()["sha"]
        r = self.http.put(f"/repos/{full_name}/contents/{TEMPLATE_PATH}", headers=h, json=body)
        if r.status_code >= 400:
            raise GitHubError(f"write template: {r.status_code} {r.text[:200]}")
        r = self.http.post(f"/repos/{full_name}/pulls", headers=h, json={
            "title": "Add GhostWalk postmortem issue form", "head": branch, "base": base,
            "body": "Adds `.github/ISSUE_TEMPLATE/postmortem.yml`. Issues labelled `postmortem` become proposed graph "
                    "changes in GhostWalk, which you review before anything is applied."})
        if r.status_code >= 400 and r.status_code != 422:
            raise GitHubError(f"open pull request: {r.status_code} {r.text[:200]}")
        return r.json().get("html_url") if r.status_code < 300 else f"https://github.com/{full_name}/pulls"


def template_fallback(full_name: str, branch="main"):
    """No write token: a prefilled 'create new file' link (GitHub then offers to open a PR) and the equivalent gh commands."""
    link = f"https://github.com/{full_name}/new/{branch}?filename={quote(TEMPLATE_PATH)}&value={quote(POSTMORTEM_TEMPLATE)}"
    return {"url": link, "path": TEMPLATE_PATH, "content": POSTMORTEM_TEMPLATE,
            "gh": f"gh api repos/{full_name}/contents/{TEMPLATE_PATH} -X PUT -f message='Add GhostWalk postmortem issue form' "
                  f"-f content=\"$(base64 < postmortem.yml)\" -f branch=ghostwalk/postmortem-template"}


def env_config():
    return {"app_id": os.environ.get("GITHUB_APP_ID"), "private_key": (os.environ.get("GITHUB_APP_PRIVATE_KEY") or "").replace("\\n", "\n"),
            "slug": os.environ.get("GITHUB_APP_SLUG", "ghostwalk"), "webhook_secret": os.environ.get("GITHUB_WEBHOOK_SECRET", ""),
            "pr_token": os.environ.get("GITHUB_PR_TOKEN")}
