"""Open pages of the deployed site in headless Chrome, let the app run, and check what a visitor actually sees.
    python scripts/browser_check.py https://ghostwalk-henna.vercel.app
Checks /demo (logged out: the Incidents page with a real verdict table and the Replay buttons), /signin and /signup (the sign-in components load), and /app/proof (the compare table and the replay card)."""
import html, os, pathlib, re, shutil, subprocess, sys, tempfile


def chrome():
    if os.environ.get("CHROME_PATH"):
        return os.environ["CHROME_PATH"]
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(p):
            return p
    for n in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(n):
            return shutil.which(n)
    raise SystemExit("no Chrome or Edge found")


def dom(url, budget=20000):
    prof = tempfile.mkdtemp()
    r = subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-sandbox", f"--user-data-dir={prof}", f"--virtual-time-budget={budget}", "--dump-dom", url], capture_output=True, text=True, encoding="utf8", timeout=120)
    return r.stdout


def text(d):
    d = re.sub(r"<script.*?</script>|<style.*?</style>", " ", d, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", d)))


def main():
    base = sys.argv[1].rstrip("/")
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label} {detail}")
    t = text(dom(base + "/demo"))
    check("/demo logged out: the Incidents page renders", "Incidents" in t and "Open now" in t, f"({len(t)} chars of text)")
    check("/demo: incidents from the demo workspace are listed", bool(re.search(r"INC-\d{4}", t)))
    check("/demo: the Replay buttons are there", "Replay Cloudflare" in t and "Replay AWS" in t)
    s = text(dom(base + "/signup"))
    check("/signup: the sign-up component loads", bool(re.search(r"Sign up|Create your account|Continue", s)), f"({s[:90]!r})")
    s = text(dom(base + "/signin"))
    check("/signin: the sign-in component loads", bool(re.search(r"Sign in|Continue|Welcome back", s)), f"({s[:90]!r})")
    p = text(dom(base + "/proof"))
    check("/proof (public): the compare table and the replay card", "How GhostWalk compares" in p and "Real-outage replays" in p, f"({len(p)} chars)")
    print("BROWSER CHECK " + ("PASSED" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
