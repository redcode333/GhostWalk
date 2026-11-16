"""Per-user workspaces. Every signed-in user gets their own Workspace (own state file, own company in HydraDB under its own id range); the public demo is one more workspace that nobody owns.

    registry (JSON, atomic):  {"next_run": 102, "users": {"<clerk user id>": {"id": "w1", "run": 101, "created": ...}}}

Isolation in HydraDB is by id range and by the company property: a workspace's HydraGraph only ever reads and writes ids inside run_id * RUN_SPAN, and every scan filters on its own `co`.
tests/test_isolation.py checks that a second workspace sees none of the first one's graph, lessons, incidents or tokens."""
from __future__ import annotations
import json, os, pathlib, threading, time
from .auth import secret_matches, split_token

DEMO_ID = "demo"


class Tenancy:
    def __init__(self, root: pathlib.Path, make_workspace, demo):
        """make_workspace(wsid, run_id, state_path) -> Workspace. demo: the public workspace (already built)."""
        self.root = pathlib.Path(root)
        (self.root / "ws").mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / "workspaces.json"
        self.make = make_workspace
        self.demo = demo
        self.lock = threading.RLock()
        self.cache: dict[str, object] = {DEMO_ID: demo}
        self.reg = json.loads(self.registry_path.read_text(encoding="utf8")) if self.registry_path.exists() else {"next_run": 101, "users": {}}

    def _save(self):
        tmp = self.registry_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.reg), encoding="utf8")
        os.replace(tmp, self.registry_path)

    def _open(self, wsid: str, run: int):
        if wsid not in self.cache:
            self.cache[wsid] = self.make(wsid, run, self.root / "ws" / f"{wsid}.json")
        return self.cache[wsid]

    def for_user(self, sub: str):
        """The signed-in user's workspace, created on first sight (empty: they load a sample or import their map)."""
        with self.lock:
            u = self.reg["users"].get(sub)
            if u is None:
                n = len(self.reg["users"]) + 1
                u = {"id": f"w{n}", "run": self.reg["next_run"], "created": time.time()}
                self.reg["next_run"] += 1
                self.reg["users"][sub] = u
                self._save()
            return self._open(u["id"], u["run"])

    def by_token(self, token: str):
        """The workspace a `gw_live_<id>_<secret>` token belongs to, or None. The demo workspace has no token."""
        wsid, secret = split_token(token)
        if not wsid:
            return None
        with self.lock:
            for u in self.reg["users"].values():
                if u["id"] == wsid:
                    ws = self._open(u["id"], u["run"])
                    return ws if secret_matches(secret, ws.token_hash) else None
        return None

    def by_installation(self, installation_id: int):
        """Resolve a verified GitHub webhook to the workspace that installed this App."""
        with self.lock:
            match = None
            for u in self.reg["users"].values():
                ws = self._open(u["id"], u["run"])
                if ws.installation and int(ws.installation.get("id", -1)) == int(installation_id):
                    if match is not None and match.wsid != ws.wsid:
                        return None                         # ambiguous ownership: fail closed
                    match = ws
            return match

    def can_claim_installation(self, installation_id: int, wsid: str):
        """An installation belongs to one workspace because GitHub webhooks carry no Clerk user ID."""
        with self.lock:
            for u in self.reg["users"].values():
                ws = self._open(u["id"], u["run"])
                if ws.installation and int(ws.installation.get("id", -1)) == int(installation_id) and ws.wsid != wsid:
                    return False
            return True
