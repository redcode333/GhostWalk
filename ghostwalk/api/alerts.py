"""Normalise alert webhooks (Alertmanager, Grafana, UptimeRobot, PagerDuty-style, generic) to
[{"name": <service>, "signal": <str>, "t": <seconds from the first alert>}]."""
from __future__ import annotations
import datetime

SERVICE_KEYS = ("service", "app", "application", "deployment", "job", "component", "pod", "instance")


def _ts(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _service(labels: dict):
    for k in SERVICE_KEYS:
        v = labels.get(k)
        if v:
            v = str(v).split(":")[0]
            return v.rsplit("-", 2)[0] if k == "pod" and v.count("-") >= 2 else v
    return None


def normalize(payload):
    """Accepts a dict or a list. Raises ValueError when nothing usable is found."""
    items = payload if isinstance(payload, list) else (payload.get("alerts") or payload.get("incidents") or [payload])
    rows = []
    for i, a in enumerate(items):
        if not isinstance(a, dict):
            continue
        labels = a.get("labels") or {}
        if (a.get("status") or "").lower() == "resolved":
            continue
        name = _service(labels) or a.get("name") or a.get("service") or a.get("monitorFriendlyName") or a.get("monitor") \
            or (a.get("incident") or {}).get("service", {}).get("summary") or labels.get("alertname")
        if not name:
            continue
        signal = labels.get("alertname") or a.get("signal") or a.get("alertTypeFriendlyName") or a.get("alertType") or "alert"
        t = a.get("t")
        if t is None:
            t = _ts(a.get("startsAt") or a.get("activeAt") or a.get("created_at"))
        rows.append({"name": str(name), "signal": str(signal), "t": t, "_i": i})
    if not rows:
        raise ValueError("no firing alerts with a service name in this payload")
    stamped = [r["t"] for r in rows if r["t"] is not None]
    base = min(stamped) if stamped else 0.0
    out = [{"name": r["name"], "signal": r["signal"], "t": round((r["t"] - base) if r["t"] is not None and stamped else float(r["_i"]), 1),
            **({"epoch": r["t"]} if r["t"] is not None and stamped and r["t"] > 1e9 else {})} for r in rows]
    return sorted(out, key=lambda r: r["t"])
