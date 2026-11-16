"""End-to-end smoke test of a deployed GhostWalk.

    python deploy/smoke.py --api https://api.1.2.3.4.sslip.io [--frontend https://ghostwalk.vercel.app]

With --frontend the API calls carry that Origin (so CORS is exercised as the browser would) and the landing page and its built bundle are checked too.
The flow: health, a verdict from a demo outage, learn (preview -> queue -> apply) which answers at once with saving, the revision bumping when the HydraDB
write lands, why-edge on a learned edge, the sandbox guard (settings 403) and, with --rate-limit-check, the rate limit (429). Exit code 1 if any step fails."""
import argparse, re, sys, time
import httpx

ok = True


def step(label, fn):
    global ok
    t = time.time()
    try:
        detail = fn()
        print(f"  PASS  {label:<46} {detail or ''} ({(time.time() - t) * 1000:.0f} ms)", flush=True)
    except Exception as e:                                                     # noqa: BLE001
        ok = False
        print(f"  FAIL  {label:<46} {str(e)[:200]}", flush=True)


def need(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--frontend", default=None)
    ap.add_argument("--insecure", action="store_true", help="do not verify the TLS certificate (a local Caddy CA)")
    ap.add_argument("--rate-limit-check", action="store_true", help="also fire a burst at /v1/ to see the 429 (uses up the budget for a minute)")
    a = ap.parse_args()
    api = a.api.rstrip("/")
    fe = a.frontend.rstrip("/") if a.frontend else None
    c = httpx.Client(timeout=60, headers={**({"Origin": fe} if fe else {}), "X-GW-Demo": "1"}, follow_redirects=True, verify=not a.insecure)       # the public demo workspace (a no-op unless sign-in is on)
    st = {}

    if fe:
        def landing():
            r = c.get(fe, headers={})
            r.raise_for_status()
            js = re.findall(r'src="(/assets/[^"]+\.js)"', r.text)
            need(js, "no bundle script in the landing page")
            need(api in c.get(fe + js[0], headers={}).text, "the bundle was not built with VITE_API_URL=" + api)
            return "landing loads, bundle points at the API"
        step("frontend: landing loads", landing)
        step("frontend: /demo serves the app (SPA rewrite)", lambda: c.get(fe + "/demo", headers={}).raise_for_status() and "200")

    def health():
        j = c.get(api + "/api/health").raise_for_status().json()
        need(j["ok"], j)
        st["health"] = j
        return f"store={j['store']} revision={j['revision']}"
    step("api: health over HTTPS", health)
    step("api: the store is HydraDB", lambda: need(st["health"]["store"] == "hydradb", st["health"]["store"]))
    if fe:
        def cors():
            r = c.options(api + "/api/summary", headers={"Origin": fe, "Access-Control-Request-Method": "GET"})
            need(r.headers.get("access-control-allow-origin") == fe, dict(r.headers))
            bad = c.options(api + "/api/summary", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
            need(bad.headers.get("access-control-allow-origin") is None, "CORS allows a foreign origin")
            return "allowed for the frontend, refused for others"
        step("api: CORS", cors)
    step("api: results.json (proof) served", lambda: f"{c.get(api + '/api/proof').raise_for_status().json()['meta']['companies']} held-out companies")

    def outage():
        inc = c.post(api + "/api/incidents/trigger").raise_for_status().json()["id"]
        v = c.get(f"{api}/api/incidents/{inc}").raise_for_status().json()["verdict"]
        need(v["root_name"], v)
        st["inc"], st["root"] = inc, v["root_name"]
        return f"{inc}: root {v['root_name']} confidence {v['confidence']:.2f} in {v['ms']:.1f} ms"
    step("demo outage -> a verdict returns", outage)

    def learn():
        body = {"root": st["root"], "path": "", "missed": ""}
        c.post(f"{api}/api/learn/{st['inc']}/preview", json=body).raise_for_status()
        q = c.post(f"{api}/api/learn/{st['inc']}/queue", json=body).raise_for_status().json()
        before = c.get(api + "/api/summary").json()["revision"]
        t = time.time()
        r = c.post(f"{api}/api/learn/pending/{q['id']}/apply", json={"reject": []}).raise_for_status().json()
        answered = (time.time() - t) * 1000
        need(r.get("saving") is True, r)
        s = {}
        for _ in range(240):
            s = c.get(api + "/api/summary").json()
            if not s["saving"]:
                break
            time.sleep(0.5)
        need(not s["saving"] and s["revision"] == before + 1, (before, s.get("revision"), s.get("saving")))
        return f"answered in {answered:.0f} ms (saving), revision {before} -> {s['revision']}"
    step("learn: apply answers at once, revision bumps when saved", learn)

    def why_edge():
        m = c.get(api + "/api/map").raise_for_status().json()
        names = {n["id"]: n["name"] for n in m["nodes"]}
        for e in m["learned"]:
            r = c.get(f"{api}/v1/edges/{names[e['u']]}/{names[e['v']]}/why")
            if r.status_code == 200 and r.json()["lessons"]:
                return r.json()["explanation"][:100]
        raise AssertionError("no learned edge has a lesson")
    step("why-edge answers for a learned edge", why_edge)
    step("sandbox: settings are read-only (403)", lambda: need(c.post(api + "/api/settings/reset-learned").status_code == 403, "settings were writable"))
    if a.rate_limit_check:
        def burst():
            codes = [httpx.get(api + "/v1/edges/a/b/why", timeout=20, verify=not a.insecure).status_code for _ in range(150)]
            need(429 in codes, "no 429 after 150 requests")
            return f"429 after {codes.index(429)} requests"
        step("rate limit on /v1/*", burst)
    print("SMOKE TEST " + ("PASSED" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
