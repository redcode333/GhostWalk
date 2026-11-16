"""Parse every ```mermaid block in README.md and docs/*.md with Mermaid itself (headless Chrome or Edge, mermaid from a CDN, a pinned version) and fail on any syntax error.
    python scripts/lint_mermaid.py            (CHROME_PATH overrides the browser)
It also renders each diagram to SVG, because some errors only appear at render time."""
import html, json, os, pathlib, re, shutil, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parent.parent
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.0/dist/mermaid.min.js"


def chrome():
    if os.environ.get("CHROME_PATH"):
        return os.environ["CHROME_PATH"]
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(p):
            return p
    for n in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        if shutil.which(n):
            return shutil.which(n)
    raise SystemExit("no Chrome or Edge found (set CHROME_PATH)")


def blocks():
    out = []
    for f in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        for i, m in enumerate(re.finditer(r"```mermaid\n(.*?)```", f.read_text(encoding="utf8"), re.S)):
            out.append((f"{f.relative_to(ROOT)}#{i + 1}", m.group(1)))
    return out


def main():
    bl = blocks()
    if not bl:
        raise SystemExit("no mermaid blocks found")
    page = f"""<!doctype html><meta charset="utf-8"><body><pre id="out">pending</pre>
<script src="{MERMAID}"></script>
<script>
const blocks = {json.dumps([b for _, b in bl])};
(async () => {{
  mermaid.initialize({{ startOnLoad: false, securityLevel: "strict" }});
  const res = [];
  for (let i = 0; i < blocks.length; i++) {{
    try {{ await mermaid.parse(blocks[i]); const r = await mermaid.render("d" + i, blocks[i]); res.push("OK " + i + " svg=" + r.svg.length); }}
    catch (e) {{ res.push("ERR " + i + " " + String(e.message || e).split("\\n").slice(0, 3).join(" | ")); }}
  }}
  document.getElementById("out").textContent = "DONE\\n" + res.join("\\n");
}})();
</script>"""
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "m.html").write_text(page, encoding="utf8")
    r = subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=30000", "--dump-dom", (d / "m.html").as_uri()], capture_output=True, text=True, encoding="utf8", timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', r.stdout, re.S)
    text = html.unescape(m.group(1)) if m else "no output"
    lines = text.splitlines()
    if not lines or lines[0] != "DONE":
        print("mermaid did not finish (is the CDN reachable?):", text[:300])
        sys.exit(2)
    bad = 0
    for (name, _), line in zip(bl, lines[1:]):
        print(f"  {'ok ' if line.startswith('OK') else 'BAD'} {name}  {line[line.index(' ', 3) + 1:][:160] if line.startswith('ERR') else ''}")
        bad += line.startswith("ERR")
    print(f"{len(bl) - bad} of {len(bl)} diagrams parse and render")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
