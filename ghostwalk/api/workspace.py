"""One workspace: a graph, its incidents, pending learner proposals, and the onboarding state.

The graph is the in-memory GraphState (the same object the evaluation uses). The demo workspace is the simulated
company `acme-demo` (80 services); accepting an onboarding map replaces it with the accepted edges.
State is saved to a JSON file after every change, so a restart keeps the learned graph.

GW_STORE=hydradb: HydraDB holds the graph AND the learner's memory (incidents, alerts, postmortems, lessons). Every learner write goes to HydraDB
first (hydra.apply), the in-memory GraphState is a cache that is rebuilt from HydraDB whenever its revision differs, and a restarted process
re-attaches to HydraDB and reads the learned graph back (the state file is not needed for it).
"""
from __future__ import annotations
import json, math, os, pathlib, random, secrets, threading, time
from ..engine.walk import walk, resolve, _limited_best, changes_before, change_note, tuned_changes
from ..graph.state import GraphState, Edge, W0_OFFICIAL, W_TENTATIVE
from ..learn import update
from ..integrations import issues

UI_KIND = {"datastore": "data", "cache": "data", "queue": "data", "shared": "infra", "external": "infra", "service": "service"}
TIER_OF = {"edge": 0, "service": 1, "data": 2, "infra": 3}
VISIBLE_OPS = ("add_edge", "confirm", "reweight", "drop_edge", "alias")


def ui_kind(c):
    return "edge" if c["kind"] == "service" and c["tier"] == 0 else UI_KIND.get(c["kind"], c["kind"])


class Workspace:
    def __init__(self, state_path=None, demo_incidents=30, seed=7777, demo=True, use_changes=None, store=None, hydra=None):
        self.lock = threading.RLock()
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
        self.token = "gw_live_" + secrets.token_hex(16)
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
            if demo:
                self._seed_demo(seed, demo_incidents)
            else:
                self.g, self.mode = GraphState(components={}), "imported"
            self.save()

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

    def _seed_demo(self, seed, n_history):
        from gwsim.cli import make
        co = json.loads(make("hub", seed, 80).to_json())
        co["name"] = "acme-demo"
        self.company = co
        self.mode = "demo"
        self.g = GraphState.from_official({"components": [{k: c[k] for k in ("id", "name", "kind", "tier")} for c in co["components"]],
                                           "edges": co["official_edges"]})
        self.incidents, self.pending, self.next_sim, self.revision = [], [], 0, 0
        if self.hy is not None:
            self._hy_reload(co)
        for _ in range(n_history):                # history: past incidents whose postmortems were applied
            inc = self._ingest(co["incidents"][self.next_sim]["alerts"], started=-(n_history - self.next_sim) * 86400 * 0.4)
            pm = co["incidents"][self.next_sim]["postmortem"]
            self._apply_pm(inc, pm)
            self.next_sim += 1
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

    def _apply_pm(self, inc, pm, reject=()):
        ops = update.propose(self.g, pm, walk(self.g, inc["alerts"]), inc["alerts"], self.g.seq)
        keep = [o for i, o in enumerate(ops) if i not in set(reject)]
        self.learned_by[self.g.seq] = inc["id"]
        self._hy_apply(keep, inc, pm)
        update.apply(self.g, keep)
        self.revision += 1
        inc["status"], inc["postmortem_applied"] = "Resolved", True
        inc["confirmed_root"] = self._name(pm["root"]) if pm.get("root") is not None else None
        rk = [r["id"] for r in inc["verdict"]["ranking"]]
        inc["checks_to_root"] = rk.index(pm["root"]) + 1 if pm.get("root") in rk else None
        inc["learned_changes"] = len([o for o in keep if self._label_safe(o)])
        return keep

    def _label_safe(self, o):
        return o["op"] in VISIBLE_OPS

    def apply_pending(self, pid, reject=()):
        with self.lock:
            item = next((p for p in self.pending if p["id"] == pid), None)
            if item is None:
                raise KeyError(pid)
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

    def reset_learned(self):
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
                "pending": len(self.pending), "onboarding": self.onboarding, "demo_outages_left": (len(self.company["incidents"]) - self.next_sim) if self.company else 0}

    # ---- persistence -----------------------------------------------------------------------
    def dump(self):
        g = self.g
        return {"mode": self.mode, "revision": self.revision, "token": self.token, "next_sim": self.next_sim, "onboarding": self.onboarding,
                "changes": self.changes, "installation": self.installation, "repo_for_template": self.repo_for_template, "map_proposals": self.map_proposals,
                "components": {str(i): c for i, c in g.components.items()}, "names": g.names,
                "edges": [[u, v, e.w, e.origin, e.confirmations, e.learned_from, e.created_seq] for (u, v), e in g.edges.items()],
                "root_counts": g.root_counts, "affected": g.affected, "missed": g.missed, "seq": g.seq, "learned_by": self.learned_by,
                "shortcuts": [[a, b, n] for (a, b), n in g.shortcuts.items()], "incidents": self.incidents, "pending": self.pending}

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
            self.g, self.mode, self.revision, self.token = g, d["mode"], d["revision"], d["token"]
            self.changes = d.get("changes", [])
            self.next_sim, self.onboarding, self.installation = d["next_sim"], d["onboarding"], d.get("installation")
            self.repo_for_template, self.map_proposals = d.get("repo_for_template"), d.get("map_proposals")
            self.incidents, self.pending = d["incidents"], d["pending"]
            if self.mode == "demo":
                from gwsim.cli import make
                self.company = json.loads(make("hub", 7777, 80).to_json())
            return True
        except Exception as e:                        # a corrupt state file must not brick the app
            self.log.append(f"state file ignored: {e}")
            return False
