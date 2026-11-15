"""A GitHub issue labelled `postmortem` (the 3-field issue form) -> a postmortem dict + learner proposals.

Issue forms render as markdown: `### <label>` followed by the answer. Fields, in order:
  Actual root cause | How it reached the alerting service | What the map got wrong (optional)
Nothing is applied here: the proposals land in the review queue.
"""
from __future__ import annotations
import difflib, re

FIELDS = {"root": "Actual root cause", "path": "How it reached the alerting service", "missed": "What the map got wrong (optional)"}
ARROW = re.compile(r"\s*(?:⇢|→|->|=>|-->|>|,)\s*")
INC = re.compile(r"\bINC-\d+\b", re.I)
ALIAS_PAT = [re.compile(r"""["'`]([\w.-]+)["'`]\s+(?:is|=|means|alias of|is an alias of|->|→)\s+(?:an? alias of\s+)?["'`]?([\w.-]+)""", re.I),
             re.compile(r"""([\w.-]+)\s+is\s+(?:also\s+)?(?:called|named|known as)\s+["'`]([\w.-]+)["'`]""", re.I)]
NO_RESPONSE = {"", "_no response_", "no response", "n/a", "none"}


def parse_issue_form(body: str) -> dict:
    sections, cur = {}, None
    for line in (body or "").replace("\r", "").split("\n"):
        m = re.match(r"^###\s+(.*\S)\s*$", line)
        if m:
            cur = m.group(1).strip()
            sections[cur] = []
        elif cur is not None:
            sections[cur].append(line)
    out = {}
    for key, label in FIELDS.items():
        text = "\n".join(next((v for k, v in sections.items() if k.lower().startswith(label.lower()[:20])), [])).strip()
        out[key] = "" if text.lower() in NO_RESPONSE else text
    return out


def resolve_name(name, names: dict, cutoff=0.82):
    """Exact name or alias, then a close match. Returns (component id | None, how)."""
    n = name.strip().strip("`'\"").lower()
    exact = {k.lower(): v for k, v in names.items()}
    if n in exact:
        return exact[n], "exact"
    close = difflib.get_close_matches(n, list(exact), n=1, cutoff=cutoff)
    return (exact[close[0]], f"matched {close[0]}") if close else (None, "unknown")


def to_postmortem(fields: dict, names: dict) -> dict:
    """-> {"root", "chain", "aliases", "unresolved"} in the learner's format. chain edges are [dependent, dependency]."""
    root, _ = resolve_name(fields.get("root", ""), names)
    hops, unresolved = [], []
    for part in ARROW.split(fields.get("path", "")):
        part = part.strip()
        if not part:
            continue
        cid, _ = resolve_name(part, names)
        if cid is None:
            unresolved.append(part)
        elif not hops or hops[-1] != cid:
            hops.append(cid)
    if root is not None and (not hops or hops[0] != root):
        hops.insert(0, root)
    chain = [[hops[i + 1], hops[i]] for i in range(len(hops) - 1)]      # root first: each next hop depends on the previous
    aliases, text = [], fields.get("missed", "")
    for pat in ALIAS_PAT:
        for a, b in pat.findall(text):
            for alias, target in ((a, b), (b, a)):
                cid, how = resolve_name(target, names)
                if cid is not None and alias.lower() not in {k.lower() for k in names}:
                    aliases.append([alias, cid])
                    break
    # explicit dependency sentences: "X reads/calls/depends on Y"
    for a, b in re.findall(r"([\w.-]+)\s+(?:reads|calls|depends on|uses|talks to|queries)\s+(?:\w+\s+)*?(?:from\s+)?([\w.-]+)", text):
        ca, cb = resolve_name(a, names, 0.95)[0], resolve_name(b, names, 0.95)[0]
        if ca is not None and cb is not None and ca != cb and [ca, cb] not in chain:
            chain.append([ca, cb])
    return {"root": root, "chain": chain, "aliases": aliases, "unresolved": unresolved, "correct": True}


def incident_ref(title: str, body: str):
    m = INC.search(title or "") or INC.search(body or "")
    return m.group(0).upper() if m else None


def is_postmortem_event(payload: dict) -> bool:
    """`issues` webhook: labelled/opened/edited/reopened, and the issue carries the `postmortem` label."""
    if payload.get("action") not in ("labeled", "opened", "edited", "reopened"):
        return False
    labels = {l.get("name", "").lower() for l in (payload.get("issue") or {}).get("labels", [])}
    if payload.get("action") == "labeled" and (payload.get("label") or {}).get("name", "").lower() != "postmortem":
        return False
    return "postmortem" in labels
