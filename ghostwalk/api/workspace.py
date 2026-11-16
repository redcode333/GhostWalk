"""One workspace: a graph, its incidents, pending learner proposals, and the onboarding state.

The graph is the in-memory GraphState (the same object the evaluation uses). The demo workspace is the simulated
company `acme-demo` (80 services); accepting an onboarding map replaces it with the accepted edges.
State is saved to a JSON file after every change, so a restart keeps the learned graph.

GW_STORE=hydradb: HydraDB holds the graph AND the learner's memory (incidents, alerts, postmortems, lessons). Every learner write goes to HydraDB
first (hydra.apply), the in-memory GraphState is a cache that is rebuilt from HydraDB whenever its revision differs, and a restarted process
re-attaches to HydraDB and reads the learned graph back (the state file is not needed for it).
"""
from __future__ import annotations
import json, math, os, pathlib, queue, random, secrets, threading, time
from ..engine.walk import walk, resolve, _limited_best, changes_before, change_note, tuned_changes
from ..graph.state import GraphState, Edge, W0_OFFICIAL, W_TENTATIVE
from ..learn import update
from ..integrations import issues
from .auth import new_token, split_token, secret_matches

FREE_SERVICES = 25
SAMPLE_SERVICES = 24          # the sample company loaded into a user's workspace fits the free plan

UI_KIND = {"datastore": "data", "cache": "data", "queue": "data", "shared": "infra", "external": "infra", "service": "service"}
TIER_OF = {"edge": 0, "service": 1, "data": 2, "infra": 3}
VISIBLE_OPS = ("add_edge", "confirm", "reweight", "drop_edge", "alias")


def ui_kind(c):
    return "edge" if c["kind"] == "service" and c["tier"] == 0 else UI_KIND.get(c["kind"], c["kind"])


class Workspace:
    def __init__(self, state_path=None, demo_incidents=30, seed=7777, demo=True, use_changes=None, store=None, hydra=None, worker=True, wsid="default"):
        self.lock = threading.RLock()
        self.jobs: list[dict] = []                # learning writes accepted but not yet in HydraDB (journalled in the state file, replayed on restart)
        self._q: queue.Queue = queue.Queue()
        self._worker = None
        self._seeding = False
        self.worker_error = None
        self.store = store or os.environ.get("GW_STORE", "memory")
        self.hy = None
        if self.store == "hydradb":
            from ..graph.hydra import HydraGraph, RUN_SPAN
            run = int(os.environ.get("GW_HYDRA_RUN", "1"))
            self.hy = hydra or HydraGraph(os.environ.get("HYDRA_URL", "http://127.0.0.1:8443"), os.environ.get("HYDRA_TOKEN", "local-development-token-32-bytes"),
                                          run_id=run, mode="cached")
            self.hy_base = self.hy.run_id * RUN_SPAN
        self.path = pathlib.Path(state_path) if state_path else None
        self.rng = random.Random(seed)
        self.mode = "demo"                       # demo | imported
        self.revision = 0
        self.wsid = wsid
        self.token_hash, self.token_tail = None, ""      # only a hash of the API token is kept; the token itself is shown once, when it is issued
        self.sample = None                               # {"seed", "size"} when a sample company was loaded into this workspace
        self.g: GraphState | None = None
        self.company = None
        self.next_sim = 0
        self.incidents: list[dict] = []
        self.pending: list[dict] = []            # learner proposals waiting for review
        self.map_proposals = None                # onboarding scan result (not official until accepted)
        self.onboarding = {"github": False, "map": False, "alert": False, "postmortem": False, "first_alert_at": None}
        self.installation = None
        self.repo_for_template = None
        self.log: list[str] = []
        self.changes: list[dict] = []             # deploy/config events: {service, ts (epoch s), kind, ref}
        self.use_changes = use_changes if use_changes is not None else os.environ.get("GW_USE_CHANGES") == "1"
        self.learned_by: dict[int, str] = {}      # graph revision -> the incident whose postmortem produced it
        loaded = bool(self.path and self.path.exists() and self._load())
        if self.hy is not None and self.hy.attach(self.hy_base):       # HydraDB already holds this workspace: it is the source of truth
            self._pull()
            if not loaded:
                from gwsim.cli import make
                self.mode, self.company = "demo", json.loads(make("hub", seed, 80).to_json())
                self.next_sim = self.hy._rows("MATCH (i:Incident {co: $co}) RETURN count(*) AS c", co=self.hy_base)[0][0]
                self.log.append("state restored from HydraDB (no state file)")
            self.save()
        elif not loaded or self.hy is not None:
            self.jobs = []                                              # nothing in HydraDB to replay them onto
            if demo:
                self._seed_demo(seed, demo_incidents)
            else:
                self.g, self.mode = GraphState(components={}), "imported"
            self.save()
        if self.token_hash is None:
            new, self.token_hash = new_token(self.wsid)
            self.token_tail = new[-4:]
            self.save()
        if self.hy is not None and worker:
            self.start_worker()

    # ---- demo seed -------------------------------------------------------------------------
    # ---- HydraDB as the store --------------------------------------------------------------
    def _pull(self):
        """The in-memory graph is a cache of HydraDB: rebuild it when its revision differs."""
        self.g = self.hy._copy(self.hy.snapshot())

    def _sync(self):
        if self.hy is not None and self.hy.co is not None and self.hy.revision() != self.g.seq:
            self._pull()

    def _co_dict(self):
        g = self.g
        return {"components": [{"id": i, "name": c["name"], "kind": c["kind"], "tier": c["tier"]} for i, c in sorted(g.components.items())],
                "official_edges": [{"u": u, "v": v} for (u, v), e in g.edges.items() if e.origin == "official"]}

    def _hy_reload(self, co):
        """A new official graph: replace everything HydraDB holds for this workspace."""
        if self.hy is None:
            return
        if self.hy.co is None:
            self.hy.co = self.hy_base
        self.hy.drop()
        self.hy.fresh(co, index=0)
        self._pull()

    # ---- the learning queue: accept now, write to HydraDB in order, bump the revision when done ------------
    @staticmethod
    def _absolute(g, ops):
        """Give every increment in `ops` its absolute target value, computed from the committed graph `g` BEFORE anything is written.
        A job that dies half-way and is replayed then writes the same values again instead of counting twice."""
        conf = {k: e.confirmations for k, e in g.edges.items()}
        rc, aff, miss, sc = dict(g.root_counts), dict(g.affected), dict(g.missed), dict(g.shortcuts)
        for o in ops:
            k = o["op"]
            if k == "confirm":
                conf[(o["u"], o["v"])] = o["conf"] = conf.get((o["u"], o["v"]), 0) + 1
            elif k == "add_edge":
                conf[(o["u"], o["v"])] = 1
            elif k == "root":
                rc[o["id"]] = o["rc"] = rc.get(o["id"], 0) + 1
            elif k == "shortcut":
                key = (o["entry"], o["root"])
                sc[key] = o["n"] = sc.get(key, 0) + 1
            elif k == "observe":
                aff[o["id"]] = o["aff"] = aff.get(o["id"], 0) + 1
                miss[o["id"]] = o["miss"] = miss.get(o["id"], 0) + (1 if o["silent"] else 0)
        return ops

    def start_worker(self):
        for j in list(self.jobs):                                       # journalled jobs from before a restart are finished BEFORE the API serves anything
            try:
                self._run_job(j)
            except Exception as e:                                      # noqa: BLE001
                self.worker_error = f"{type(e).__name__}: {e}"
                self.log.append(f"replay stopped: {self.worker_error}")
                return
        self._worker = threading.Thread(target=self._work, name="gw-learn-writer", daemon=True)
        self._worker.start()

    def _work(self):
        while True:
            jid = self._q.get()
            if jid is None:
                return
            job = next((j for j in self.jobs if j["id"] == jid), None)
            if job is None:
                continue
            try:
                self._run_job(job)
            except Exception as e:                                      # leave the job journalled: the next start replays it
                self.worker_error = f"{type(e).__name__}: {e}"
                self.log.append(f"learning writer stopped: {self.worker_error}")
                import logging
                logging.getLogger("uvicorn.error").error("LEARNING WRITER STOPPED (the job stays journalled and is replayed on restart): %s", self.worker_error[:300])
                return

    def _run_job(self, job):
        with self.lock:
            rev = self.hy.revision()
            if job["expect_rev"] < rev:                                 # already in HydraDB (the process died after the revision bump)
                self.jobs.remove(job)
                self._pull()
                self.save()
                return
            if self.g.seq != rev:
                self._pull()
            inc = self.get(job["incident"]) if job["incident"] else None
            if "started" in job:                                        # a replay: the operations (with absolute values) were fixed before the first write
                keep, seq = job["started"]["ops"], job["started"]["seq"]
            else:
                keep = self._pm_ops(inc, job["pm"], job["reject"]) if inc is not None else job["ops"]
                keep = self._absolute(self.g, keep)
                seq = self.g.seq
                job["started"] = {"ops": keep, "seq": seq}
                self.save()                                             # journalled before the first HydraDB write
            payload = {"seq": seq, "name": inc["id"], "alerts": inc["alerts"], "postmortem": job["pm"]} if inc is not None else None
        self.hy.apply(keep, incident=payload)                           # the slow part, outside the workspace lock; verdicts keep reading the committed graph
        with self.lock:
            self._pull()                                                # the write-through cache already holds the new revision
            self.revision += 1
            if inc is not None:
                self.learned_by[seq] = inc["id"]
                self._pm_done(inc, job["pm"], keep)
            self.jobs.remove(job)
            self.save()

    def wait_saved(self, timeout=60.0):
        """Block until every accepted learning write is in HydraDB (tests, scripts)."""
        end = time.time() + timeout
        while self.jobs and time.time() < end:
            if self.worker_error:
                raise RuntimeError(self.worker_error)
            time.sleep(0.05)
        return not self.jobs

    def enqueue_learning(self, item, reject):
        inc = self.get(item["incident"]) if item["incident"] else None
        job = {"id": secrets.token_hex(4), "incident": inc["id"] if inc else None, "pm": item["pm"], "reject": list(reject),
               "ops": None if inc else [o for i, o in enumerate(item["ops"]) if i not in set(reject)],
               "expect_rev": self.g.seq + len(self.jobs)}              # the revision this write starts from
        self.jobs.append(job)
        if inc is not None:
            inc["saving"] = True
        self.save()                                                     # journalled before we answer
        if self._worker is not None:
            self._q.put(job["id"])
        return job

    def _hy_apply(self, ops, inc=None, pm=None):
        if self.hy is None:
            return
        self._sync()
        self.hy.apply(ops, incident=None if inc is None else {"seq": self.g.seq, "name": inc["id"], "alerts": inc["alerts"], "postmortem": pm})

    def why_edge(self, src, dst):
        if self.hy is None:
            raise LookupError("edge lineage lives in HydraDB: start the API with GW_STORE=hydradb")
        self._sync()
        return self.hy.why_edge(src, dst)

    def lesson_impact(self, lesson_id):
        if self.hy is None:
            raise LookupError("edge lineage lives in HydraDB: start the API with GW_STORE=hydradb")
        self._sync()
        return self.hy.lesson_impact(lesson_id)

    def _seed_demo(self, seed, n_history, size=80, name="acme-demo"):
        from gwsim.cli import make
        co = json.loads(make("hub", seed, size).to_json())
        co["name"] = name
        self.company = co
        self.mode = "demo"
        self.g = GraphState.from_official({"components": [{k: c[k] for k in ("id", "name", "kind", "tier")} for c in co["components"]],
                                           "edges": co["official_edges"]})
        self.incidents, self.pending, self.next_sim, self.revision = [], [], 0, 0
        if self.hy is not None:
            self._hy_reload(co)
        self._seeding = True
        for _ in range(n_history):                # history: past incidents whose postmortems were applied
            inc = self._ingest(co["incidents"][self.next_sim]["alerts"], started=-(n_history - self.next_sim) * 86400 * 0.4)
            pm = co["incidents"][self.next_sim]["postmortem"]
            self._apply_pm(inc, pm)
            self.next_sim += 1
        self._seeding = False
        self.incidents[-1]["status"], self.incidents[-1]["postmortem_applied"] = "Needs postmortem", False

    # ---- incidents -------------------------------------------------------------------------
    def _name(self, cid):
        return self.g.components[cid]["name"]

    def add_change(self, service, ts=None, kind="deploy", ref=""):
        """Record what changed (a deploy or config change). `service` may be an alias."""
        with self.lock:
            cid = self.g.names.get(service)
            if cid is None:
                raise ValueError(f"'{service}' is not in the map")
            ev = {"service": self.g.components[cid]["name"], "ts": float(ts if ts is not None else time.time()), "kind": kind or "deploy", "ref": ref or ""}
            self.changes.append(ev)
            self.changes = self.changes[-5000:]
            self.save()
            return ev

    def _ingest(self, alerts, started=None, source="webhook"):
        self._sync()
        t0 = time.perf_counter()
        epochs = [a["epoch"] for a in alerts if a.get("epoch")]
        first_epoch = min(epochs) if epochs else time.time() + (started or 0)
        gamma, tau = tuned_changes()
        ch = changes_before(self.g, self.changes, first_epoch) if self.use_changes and self.changes else None
        v = walk(self.g, alerts, changes=ch, gamma=gamma, tau=tau)
        ms = (time.perf_counter() - t0) * 1000
        A, unresolved, onset = resolve(self.g, alerts)
        top = v.ranking[:5]
        z = sum(math.exp(s - v.ranking[0][1]) for _, s in v.ranking) if v.ranking else 1
        ranked = [{"id": c, "name": self._name(c), "confidence": round(math.exp(s - v.ranking[0][1]) / z, 4)} for c, s in top]
        root = v.ranking[0][0] if v.ranking else None
        in_best, _ = _limited_best(self.g.in_adj(), root, 5) if root is not None else ({}, {})
        explained = sorted(x for x in A if x in in_best)
        path_ids = [v.path[0][0]] + [e[1] for e in v.path] if v.path else ([root] if root is not None else [])
        blast = sorted(set(A) | set(path_ids) | ({root} if root is not None else set()))
        seq = len(self.incidents)
        entry = v.entry
        sig = alerts[0]["signal"] if alerts else "alerts"
        inc = {"id": f"INC-{1000 + seq}", "seq": seq, "source": source,
               "symptom": f"{self._name(entry)} {sig} · {len(alerts)} alerts" if entry is not None else f"{len(alerts)} alerts, none matched the map",
               "alerts": alerts, "started": time.time() + (started or 0), "status": "Open", "postmortem_applied": False,
               "verdict": {"ranking": ranked, "root": root, "root_name": self._name(root) if root is not None else None,
                           "confidence": round(v.confidence, 4), "entry": entry, "entry_name": self._name(entry) if entry is not None else None,
                           "path": [{"u": u, "v": w, "u_name": self._name(u), "v_name": self._name(w), "origin": o} for u, w, o in v.path],
                           "unresolved": v.unresolved, "candidates": v.candidates, "ms": round(ms, 2),
                           "edges_walked": sum(len(a) for a in self.g.out_adj().values()),
                           "explains": len(explained), "of": len(A), "services": len(A),
                           "blast": [{"id": c, "name": self._name(c), "kind": ui_kind(self.g.components[c]),
                                      "alerting": c in A, "root": c == root, "onset": onset.get(c)} for c in blast],
                           "change_note": change_note(self.g, self.changes, root, first_epoch) if self.use_changes and root is not None else None,
                           "learned_on_path": [{"u": u, "v": w, "confirmations": self.g.edges[(u, w)].confirmations,
                                                "from": self.g.edges[(u, w)].learned_from,
                                                "incident": self.learned_by.get(self.g.edges[(u, w)].learned_from)}
                                               for u, w, o in v.path if o == "learned"]},
               "confirmed_root": None, "checks_to_root": None}
        self.incidents.append(inc)
        return inc

    def ingest_alerts(self, alerts, source="webhook"):
        with self.lock:
            if not alerts:
                raise ValueError("no alerts in payload")
            inc = self._ingest(alerts, source=source)
            if not self.onboarding["first_alert_at"]:
                self.onboarding["first_alert_at"], self.onboarding["alert"] = time.time(), True
            self.save()
            return inc

    def trigger_outage(self):
        """Replay the next outage of the simulated demo company through the same path a webhook takes."""
        with self.lock:
            if self.mode != "demo" or self.next_sim >= len(self.company["incidents"]):
                return self.test_alert()
            inc = self.ingest_alerts(self.company["incidents"][self.next_sim]["alerts"], source="simulated outage")
            inc["sim_seq"] = self.next_sim
            self.next_sim += 1
            self.save()
            return inc

    def test_alert(self):
        """A synthetic cascade on the CURRENT map: pick a shared dependency, alert on what depends on it."""
        with self.lock:
            g = self.g
            in_adj = g.in_adj()
            leaves = [c for c in g.components if in_adj.get(c) and g.components[c]["tier"] >= 1] or list(g.components)
            root = self.rng.choice(sorted(leaves, key=lambda c: -len(in_adj.get(c, [])))[:5])
            onset, frontier = {root: 0.0}, [root]
            while frontier and len(onset) < 8:
                x = frontier.pop(0)
                for u, _ in in_adj.get(x, []):
                    if u not in onset:
                        onset[u] = onset[x] + self.rng.uniform(8, 40)
                        frontier.append(u)
            alerts = [{"name": g.components[c]["name"], "signal": "error_rate", "t": round(t, 1)}
                      for c, t in sorted(onset.items(), key=lambda t: t[1]) if c != root or self.rng.random() > 0.2]
            if len(alerts) < 2:
                alerts = [{"name": g.components[c]["name"], "signal": "error_rate", "t": round(t, 1)} for c, t in onset.items()]
            inc = self.ingest_alerts(alerts, source="test alert")
            inc["test_root"] = self._name(root)
            self.save()
            return inc

    def get(self, inc_id):
        return next((i for i in self.incidents if i["id"].lower() == inc_id.lower()), None)

    # ---- learning --------------------------------------------------------------------------
    def make_pm(self, fields):
        return issues.to_postmortem(fields, self.g.names)

    def preview(self, inc, pm):
        """Learner ops for this postmortem, labelled for review. Nothing is applied."""
        v = None
        if inc is not None:
            from ..engine.walk import Verdict
            v = walk(self.g, inc["alerts"])
        ops = update.propose(self.g, pm, v, inc["alerts"] if inc else [], self.g.seq)
        shown = []
        for i, o in enumerate(ops):
            row = self._label(o)
            if row:
                shown.append({"index": i, **row})
        return {"ops": ops, "shown": shown, "unresolved": pm.get("unresolved", []),
                "root_name": self._name(pm["root"]) if pm.get("root") is not None else None}

    def _label(self, o):
        n = self._name
        k = o["op"]
        if k == "add_edge":
            return {"symbol": "+", "text": f"{n(o['u'])} ⇢ {n(o['v'])}", "detail": f"new · tentative {o['w']:.2f}"}
        if k == "confirm":
            e = self.g.edges[(o["u"], o["v"])]
            return {"symbol": "+", "text": f"{n(o['u'])} ⇢ {n(o['v'])}", "detail": f"confirm · {e.w:.2f} → {o['w']:.2f}"}
        if k == "reweight":
            e = self.g.edges.get((o["u"], o["v"]))
            if e is None or abs(e.w - o["w"]) < 1e-9:
                return None
            return {"symbol": "~" if o["w"] >= e.w else "−", "text": f"{n(o['u'])} → {n(o['v'])}", "detail": f"reweight · {e.w:.2f} → {o['w']:.2f}"}
        if k == "drop_edge":
            return {"symbol": "−", "text": f"{n(o['u'])} → {n(o['v'])}", "detail": "drop · kept misleading the walk"}
        if k == "alias":
            return {"symbol": "=", "text": f"\"{o['name']}\" alias of {n(o['id'])}", "detail": "alias"}
        return None

    def queue(self, inc, pm, source, ref=None):
        with self.lock:
            p = self.preview(inc, pm)
            item = {"id": secrets.token_hex(4), "incident": inc["id"] if inc else None, "ref": ref, "source": source,
                    "created": time.time(), "pm": pm, **p}
            self.pending.append(item)
            self.onboarding["postmortem"] = True
            self.save()
            return item

    def queue_edge(self, u, v, incident_id=None, reason=""):
        """A suggested dependency (u depends on v) from a person or an MCP client. PENDING only: nothing touches the graph."""
        with self.lock:
            e = self.g.edges.get((u, v))
            ops = [] if e else [{"op": "add_edge", "u": u, "v": v, "w": W_TENTATIVE, "seq": self.g.seq}]
            row = {"index": 0, "symbol": "+", "text": f"{self._name(u)} ⇢ {self._name(v)}",
                   "detail": "already in the map" if e else f"new · tentative {W_TENTATIVE:.2f}"}
            item = {"id": secrets.token_hex(4), "incident": None, "ref": incident_id, "source": "MCP client" + (f" · {reason}" if reason else ""),
                    "created": time.time(), "pm": None, "ops": ops, "shown": [row] if ops else [], "unresolved": [], "root_name": None}
            self.pending.append(item)
            self.save()
            return item

    def _pm_ops(self, inc, pm, reject=()):
        ops = update.propose(self.g, pm, walk(self.g, inc["alerts"]), inc["alerts"], self.g.seq)
        return [o for i, o in enumerate(ops) if i not in set(reject)]

    def _apply_pm(self, inc, pm, reject=()):
        keep = self._pm_ops(inc, pm, reject)
        self.learned_by[self.g.seq] = inc["id"]
        self._hy_apply(keep, inc, pm)
        update.apply(self.g, keep)
        self.revision += 1
        self._pm_done(inc, pm, keep)
        return keep

    def _pm_done(self, inc, pm, keep):
        inc.pop("saving", None)
        inc["status"], inc["postmortem_applied"] = "Resolved", True
        inc["confirmed_root"] = self._name(pm["root"]) if pm.get("root") is not None else None
        rk = [r["id"] for r in inc["verdict"]["ranking"]]
        inc["checks_to_root"] = rk.index(pm["root"]) + 1 if pm.get("root") in rk else None
        inc["learned_changes"] = len([o for o in keep if self._label_safe(o)])

    def _label_safe(self, o):
        return o["op"] in VISIBLE_OPS

    def apply_pending(self, pid, reject=()):
        with self.lock:
            item = next((p for p in self.pending if p["id"] == pid), None)
            if item is None:
                raise KeyError(pid)
            if self.hy is not None and not self._seeding:             # HydraDB store: accept now, write in the background, bump the revision when done
                self.pending.remove(item)
                job = self.enqueue_learning(item, reject)
                return {"applied": max(0, len(item.get("ops") or []) - len(reject)), "revision": self.revision, "saving": True, "job": job["id"]}
            inc = self.get(item["incident"]) if item["incident"] else None
            if inc is not None:
                keep = self._apply_pm(inc, item["pm"], reject)
            else:
                keep = [o for i, o in enumerate(item["ops"]) if i not in set(reject)]
                self._hy_apply(keep)
                update.apply(self.g, keep)
                self.revision += 1
            self.pending.remove(item)
            self.save()
            return {"applied": len(keep), "revision": self.revision}

    def reset_demo(self):
        """Throw away everything done in the public sandbox and rebuild the seeded demo workspace (nightly)."""
        self.wait_saved()
        with self.lock:
            self.jobs, self.pending, self.changes, self.log = [], [], [], []
            self._seed_demo(7777, int(os.environ.get("GW_DEMO_INCIDENTS", "30")))
            self.save()

    def reset_learned(self):
        self.wait_saved()                          # queued learning writes land first
        with self.lock:
            for k in [k for k, e in self.g.edges.items() if e.origin == "learned"]:
                del self.g.edges[k]
            self.g.root_counts, self.g.shortcuts, self.g.affected, self.g.missed = {}, {}, {}, {}
            self.g.names = {c["name"]: i for i, c in self.g.components.items()}
            self.g.invalidate()
            if self.hy is not None:
                self._hy_reload(self._co_dict())
            self.revision += 1
            self.save()

    # ---- onboarding ------------------------------------------------------------------------
    def set_proposals(self, proposals):
        with self.lock:
            self.map_proposals = proposals
            self.save()

    def accept_map(self, edge_ids):
        """The accepted edges become the OFFICIAL map: a fresh graph at w=0.7, replacing whatever was there."""
        self.wait_saved()                          # queued learning writes land first
        with self.lock:
            if not self.map_proposals:
                raise ValueError("nothing scanned yet")
            ids = set(edge_ids)
            edges = [e for e in self.map_proposals["edges"] if e["id"] in ids]
            names = sorted({e["src"] for e in edges} | {e["dst"] for e in edges})
            kinds = {s["name"]: s["kind"] for s in self.map_proposals["services"]}
            comps = [{"id": i, "name": n, "kind": kinds.get(n, "service"), "tier": TIER_OF.get(kinds.get(n, "service"), 1)} for i, n in enumerate(names)]
            ix = {n: i for i, n in enumerate(names)}
            self.g = GraphState.from_official({"components": comps, "edges": [{"u": ix[e["src"]], "v": ix[e["dst"]]} for e in edges]})
            if self.hy is not None:
                self._hy_reload(self._co_dict())
            self.company, self.mode, self.incidents, self.pending, self.revision = None, "imported", [], [], 0
            self.onboarding.update(map=True, alert=False, first_alert_at=None)
            self.map_proposals["accepted"] = sorted(ids)
            self.save()
            return {"services": len(comps), "dependencies": len(edges)}

    # ---- views -----------------------------------------------------------------------------
    def graph_view(self):
        g = self.g
        nodes = [{"id": i, "name": c["name"], "kind": ui_kind(g.components[i]), "tier": c["tier"]} for i, c in sorted(g.components.items())]
        edges = [{"u": u, "v": v, "w": round(e.w, 3), "origin": e.origin, "confirmations": e.confirmations, "from": e.learned_from}
                 for (u, v), e in g.edges.items()]
        learned = [e for e in edges if e["origin"] == "learned"]
        return {"nodes": nodes, "edges": edges, "learned": learned, "official": len(edges) - len(learned), "revision": self.revision}

    def summary(self):
        done = [i for i in self.incidents if i["checks_to_root"] is not None][-30:]
        ms = sorted(i["verdict"]["ms"] for i in self.incidents)
        return {"workspace": "acme-demo" if self.mode == "demo" else "your workspace", "mode": self.mode,
                "services": len(self.g.components), "official_edges": sum(1 for e in self.g.edges.values() if e.origin == "official"),
                "learned_edges": sum(1 for e in self.g.edges.values() if e.origin == "learned"),
                "open": sum(1 for i in self.incidents if i["status"] == "Open"),
                "top1_last_30": (sum(1 for i in done if i["checks_to_root"] == 1) / len(done)) if done else None, "scored": len(done),
                "median_ms": ms[len(ms) // 2] if ms else None, "revision": self.revision,
                "store": {"name": self.store, "label": "HydraDB graph (memory in the graph)" if self.hy is not None else "In-memory graph"},
                "pending": len(self.pending), "saving": len(self.jobs), "onboarding": self.onboarding, "demo_outages_left": (len(self.company["incidents"]) - self.next_sim) if self.company else 0}

    # ---- API token (hashed) ----------------------------------------------------------------
    def issue_token(self) -> str:
        """A new token for this workspace. The caller shows it once; only its hash is stored."""
        tok, h = new_token(self.wsid)
        with self.lock:
            self.token_hash, self.token_tail = h, tok[-4:]
            self.save()
        return tok

    def token_ok(self, presented: str) -> bool:
        wsid, secret = split_token(presented or "")
        return (wsid is None or wsid == self.wsid) and secret_matches(secret, self.token_hash)

    @property
    def token_masked(self) -> str:
        return f"gw_live_{self.wsid}_" + "•" * 24 + self.token_tail if self.token_hash else "no token yet: rotate to create one"

    # ---- a sample company in a user's own workspace -----------------------------------------
    def load_sample(self, seed=4242, history=8):
        """Replace this workspace's graph with a small sample company (it fits the free plan), learned from a few past incidents, so a first verdict works at once."""
        self.wait_saved()
        with self.lock:
            self.sample = {"seed": seed, "size": SAMPLE_SERVICES}
            self._seed_demo(seed, history, size=SAMPLE_SERVICES, name="your-sample")
            self.mode = "sample"
            self.onboarding.update(map=True)
            self.save()
            return {"services": len(self.g.components), "dependencies": len(self.g.edges), "incidents": len(self.incidents)}

    # ---- persistence -----------------------------------------------------------------------
    def dump(self):
        g = self.g
        return {"mode": self.mode, "revision": self.revision, "token_hash": self.token_hash, "token_tail": self.token_tail, "wsid": self.wsid, "sample": self.sample, "next_sim": self.next_sim, "onboarding": self.onboarding,
                "changes": self.changes, "installation": self.installation, "repo_for_template": self.repo_for_template, "map_proposals": self.map_proposals,
                "components": {str(i): c for i, c in g.components.items()}, "names": g.names,
                "edges": [[u, v, e.w, e.origin, e.confirmations, e.learned_from, e.created_seq] for (u, v), e in g.edges.items()],
                "root_counts": g.root_counts, "affected": g.affected, "missed": g.missed, "seq": g.seq, "learned_by": self.learned_by,
                "shortcuts": [[a, b, n] for (a, b), n in g.shortcuts.items()], "incidents": self.incidents, "pending": self.pending, "jobs": self.jobs}

    def save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.dump()), encoding="utf8")
        os.replace(tmp, self.path)

    def _load(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf8"))
            g = GraphState(components={int(i): c for i, c in d["components"].items()})
            g.names = d["names"]
            for u, v, w, o, cf, lf, cs in d["edges"]:
                g.edges[(u, v)] = Edge(w, o, cf, lf, cs)
            g.root_counts = {int(k): v for k, v in d["root_counts"].items()}
            g.affected = {int(k): v for k, v in d["affected"].items()}
            g.missed = {int(k): v for k, v in d["missed"].items()}
            g.shortcuts = {(a, b): n for a, b, n in d["shortcuts"]}
            g.seq = d["seq"]
            self.learned_by = {int(k): v for k, v in d.get("learned_by", {}).items()}
            self.g, self.mode, self.revision = g, d["mode"], d["revision"]
            if d.get("token_hash"):
                self.token_hash, self.token_tail = d["token_hash"], d.get("token_tail", "")
            elif d.get("token"):                                                      # a state file from before tokens were hashed
                import hashlib
                secret = d["token"].removeprefix("gw_live_")
                self.token_hash, self.token_tail = hashlib.sha256(secret.encode()).hexdigest(), d["token"][-4:]
            self.sample = d.get("sample")
            self.changes = d.get("changes", [])
            self.next_sim, self.onboarding, self.installation = d["next_sim"], d["onboarding"], d.get("installation")
            self.repo_for_template, self.map_proposals = d.get("repo_for_template"), d.get("map_proposals")
            self.incidents, self.pending = d["incidents"], d["pending"]
            self.jobs = d.get("jobs", [])
            if self.mode == "demo":
                from gwsim.cli import make
                self.company = json.loads(make("hub", 7777, 80).to_json())
            elif self.mode == "sample" and self.sample:
                from gwsim.cli import make
                self.company = json.loads(make("hub", self.sample["seed"], self.sample["size"]).to_json())
                self.company["name"] = "your-sample"
            return True
        except Exception as e:                        # a corrupt state file must not brick the app
            self.log.append(f"state file ignored: {e}")
            return False
