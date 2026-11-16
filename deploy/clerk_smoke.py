"""Live smoke test of sign-in and workspace isolation against a deployed GhostWalk with AUTH_MODE=clerk.

    python deploy/clerk_smoke.py --api https://api.13-51-194-36.sslip.io --frontend https://ghostwalk-henna.vercel.app

Reads CLERK_SECRET_KEY from the environment or .env (never printed). It creates two throwaway users through Clerk's backend API, mints a session token for each (what the browser's Clerk SDK sends),
runs the flow, and deletes both users at the end: sign in -> an empty workspace -> load the sample company -> a verdict -> learn -> why-edge; the public demo works logged out; the second account sees none of the
first one's data; a workspace API token reaches only its own workspace. Exit code 1 if any step fails."""
import argparse, json, os, pathlib, secrets, sys, time
import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
ok = True


def env():
    e = dict(os.environ)
    p = ROOT / ".env"
    if p.exists():
        for l in p.read_text(encoding="utf8").splitlines():
            if "=" in l and not l.strip().startswith("#"):
                k, v = l.split("=", 1)
                e.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return e


def step(label, fn):
    global ok
    t = time.time()
    try:
        detail = fn()
        print(f"  PASS  {label:<56} {detail or ''} ({(time.time() - t) * 1000:.0f} ms)", flush=True)
    except Exception as e:                                                       # noqa: BLE001
        ok = False
        print(f"  FAIL  {label:<56} {str(e)[:220]}", flush=True)


def need(cond, msg="assertion failed"):
    if not cond:
        raise AssertionError(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--frontend", required=True)
    a = ap.parse_args()
    api, fe = a.api.rstrip("/"), a.frontend.rstrip("/")
    sk = env()["CLERK_SECRET_KEY"]
    clerk = httpx.Client(base_url="https://api.clerk.com/v1", headers={"authorization": f"Bearer {sk}"}, timeout=30)
    users, tokens = [], {}

    def make_user(tag):
        email = f"ghostwalk-smoke-{tag}-{secrets.token_hex(3)}@example.com"
        r = clerk.post("/users", json={"email_address": [email], "password": secrets.token_urlsafe(24), "skip_password_checks": True, "skip_password_requirement": True})
        r.raise_for_status()
        uid = r.json()["id"]
        users.append(uid)
        s = clerk.post("/sessions", json={"user_id": uid})
        s.raise_for_status()
        t = clerk.post(f"/sessions/{s.json()['id']}/tokens", json={})
        t.raise_for_status()
        tokens[tag] = t.json()["jwt"]
        return uid

    def h(tag):
        return {"Authorization": "Bearer " + tokens[tag], "Origin": fe}
    c = httpx.Client(timeout=90, follow_redirects=True)
    try:
        step("sign up two accounts (Clerk backend API) and mint sessions", lambda: f"{make_user('a')[:12]}..., {make_user('b')[:12]}...")
        step("demo works logged out (no account)", lambda: need(c.get(f"{api}/api/summary", headers={"X-GW-Demo": "1", "Origin": fe}).json()["services"] > 25) or "80-service demo workspace")
        step("no session -> 401", lambda: need(c.get(f"{api}/api/summary", headers={"Origin": fe}).status_code == 401))
        step("a forged token -> 401", lambda: need(c.get(f"{api}/api/summary", headers={"Authorization": "Bearer " + tokens["a"][:-4] + "AAAA", "Origin": fe}).status_code == 401))
        step("account A: a fresh, empty workspace", lambda: need(c.get(f"{api}/api/summary", headers=h("a")).json()["services"] == 0) or "0 services")
        step("account A: load the sample company (a small sample company)", lambda: str(c.post(f"{api}/api/onboarding/load-sample", headers=h("a")).raise_for_status().json()))
        st = {}

        def verdict():
            inc = c.post(f"{api}/api/incidents/trigger", headers=h("a")).raise_for_status().json()["id"]
            v = c.get(f"{api}/api/incidents/{inc}", headers=h("a")).raise_for_status().json()["verdict"]
            need(v["root_name"])
            st["inc"], st["root"] = inc, v["root_name"]
            return f"{inc}: root {v['root_name']} ({v['confidence']:.2f}) in {v['ms']:.1f} ms"
        step("account A: a verdict on the sample company", verdict)

        def learn():
            body = {"root": st["root"], "path": "", "missed": ""}
            q = c.post(f"{api}/api/learn/{st['inc']}/queue", json=body, headers=h("a")).raise_for_status().json()
            before = c.get(f"{api}/api/summary", headers=h("a")).json()["revision"]
            r = c.post(f"{api}/api/learn/pending/{q['id']}/apply", json={"reject": []}, headers=h("a")).raise_for_status().json()
            for _ in range(120):
                s = c.get(f"{api}/api/summary", headers=h("a")).json()
                if not s.get("saving"):
                    break
                time.sleep(0.5)
            need(s["revision"] == before + 1, (before, s["revision"]))
            return f"saving={r.get('saving')}, revision {before} -> {s['revision']}"
        step("account A: apply a postmortem (saving, then the revision moves)", learn)
        step("account B: sees none of A's data", lambda: need(c.get(f"{api}/api/summary", headers=h("b")).json()["services"] == 0 and c.get(f"{api}/api/incidents", headers=h("b")).json() == []
                                                              and c.get(f"{api}/api/incidents/{st['inc']}", headers=h("b")).status_code == 404 and c.get(f"{api}/api/map", headers=h("b")).json()["nodes"] == []) or "0 services, 0 incidents, A's incident 404")

        def token_scope():
            ta = c.post(f"{api}/api/settings/token/rotate", headers=h("a")).raise_for_status().json()["token"]
            names = [n["name"] for n in c.get(f"{api}/api/map", headers=h("a")).json()["nodes"][:3]]
            body = {"alerts": [{"name": n, "signal": "error_rate", "t": i * 5} for i, n in enumerate(names)]}
            r = c.post(f"{api}/v1/alerts/mine", json=body, headers={"Authorization": "Bearer " + ta})
            need(r.status_code == 200, r.status_code)
            need(c.post(f"{api}/v1/alerts/mine", json=body, headers={"Authorization": "Bearer " + ta[:-1] + "0"}).status_code == 401)
            need(c.post(f"{api}/v1/alerts/mine", json=body).status_code == 401)
            need(c.get(f"{api}/api/incidents", headers=h("b")).json() == [])
            return "A's token reaches A only; tampered or missing token -> 401"
        step("workspace API token (hashed, shown once) is scoped to its workspace", token_scope)
        step("the stored token cannot be shown again", lambda: need(c.post(f"{api}/api/settings/token/reveal", headers=h("a")).status_code == 410))
        step("frontend: sign-in and sign-up pages are served", lambda: need(all(c.get(fe + p).status_code == 200 for p in ("/signin", "/signup", "/demo"))))
    finally:
        for uid in users:
            clerk.delete(f"/users/{uid}")
        print(f"  cleaned up {len(users)} throwaway users", flush=True)
    print("CLERK SMOKE " + ("PASSED" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
