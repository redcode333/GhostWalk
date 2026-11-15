"""Turn infrastructure files into PROPOSED dependency edges. Nothing here writes to the graph.

Sources, strongest evidence first:
  compose depends_on          high    service A waits for service B
  k8s Ingress backend         high    the edge / ingress routes traffic to a Service
  *_URL / *_HOST env vars     medium  http(s)://host, postgres://host, redis://host ... pointing at a known service
                                      (high when the value names a service defined in the same file set and the scheme is a datastore)
  Helm values                 low     a url/host/endpoint key whose value names a known service
Every proposal carries the source repo, source file, evidence label and a confidence (high / medium / low).
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse
import yaml

CONF_SCORE = {"high": 0.9, "medium": 0.6, "low": 0.3}
_RANK = {"low": 0, "medium": 1, "high": 2}
DATA_HINTS = ("postgres", "mysql", "mariadb", "mongo", "redis", "memcache", "kafka", "rabbit", "nats", "elastic", "cassandra", "dynamo", "-db", "db-", "cache", "queue", "mq")
INFRA_HINTS = ("config", "dns", "consul", "vault", "etcd", "zookeeper", "registry", "auth-proxy", "mesh", "secrets", "feature-flag")
EDGE_HINTS = ("ingress", "gateway", "edge", "nginx", "envoy", "traefik", "haproxy", "cdn", "web-edge", "lb")
SCHEME_KIND = {"postgres": "data", "postgresql": "data", "mysql": "data", "mongodb": "data", "redis": "data", "rediss": "data",
               "amqp": "data", "kafka": "data", "memcached": "data", "nats": "data"}
URLISH_KEY = re.compile(r"(url|uri|host|hostname|endpoint|addr|address|dsn|broker|server)$", re.I)
ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*['\"]?([^'\"\s#]+)", re.M)


@dataclass
class Edge:
    src: str
    dst: str
    repo: str
    file: str
    evidence: str
    confidence: str
    sources: list = field(default_factory=list)

    @property
    def score(self):
        return CONF_SCORE[self.confidence]

    def key(self):
        return (self.src, self.dst)

    def to_dict(self):
        d = asdict(self)
        d["score"] = self.score
        d["id"] = f"{self.src}>{self.dst}"
        return d


@dataclass
class Finding:
    services: dict = field(default_factory=dict)     # name -> {"kind": ..., "repo": ..., "file": ...}
    edges: list = field(default_factory=list)
    files: list = field(default_factory=list)        # (repo, path, type)

    def add_service(self, name, kind=None, repo="", file=""):
        if not name:
            return
        cur = self.services.get(name)
        kind = kind or guess_kind(name)
        if cur is None:
            self.services[name] = {"kind": kind, "repo": repo, "file": file}
        elif cur["kind"] == "service" and kind != "service":
            cur["kind"] = kind

    def add_edge(self, src, dst, repo, file, evidence, confidence):
        if not src or not dst or src == dst:
            return
        self.add_service(src, repo=repo, file=file)
        self.add_service(dst, repo=repo, file=file)
        self.edges.append(Edge(src, dst, repo, file, evidence, confidence))


def guess_kind(name: str, image: str = "") -> str:
    s = f"{name} {image}".lower()
    if any(h in s for h in EDGE_HINTS):
        return "edge"
    if any(h in s for h in DATA_HINTS):
        return "data"
    if any(h in s for h in INFRA_HINTS):
        return "infra"
    return "service"


def classify(path: str) -> str | None:
    """What kind of file is this? None = not interesting."""
    p = path.replace("\\", "/")
    base = p.rsplit("/", 1)[-1].lower()
    if re.fullmatch(r"(docker-)?compose(\.[\w-]+)?\.ya?ml", base) or base in ("docker-compose.yml", "docker-compose.yaml"):
        return "compose"
    if re.fullmatch(r"values(-[\w.]+)?\.ya?ml", base):
        return "helm"
    if base == ".env" or base.startswith(".env.") or base.endswith(".env"):
        return "env"
    if base.endswith((".yaml", ".yml")) and re.search(r"(^|/)(k8s|kubernetes|manifests?|deploy(ment)?s?|charts/[^/]+/templates)(/|$)", p):
        return "k8s"
    return None


def _norm_host(host: str) -> str:
    """payments.prod.svc.cluster.local -> payments ; payments:8080 -> payments"""
    host = (host or "").lower().strip("[]")
    host = host.split(":")[0]
    if host in ("localhost", "127.0.0.1", "0.0.0.0", ""):
        return ""
    return host.split(".")[0] if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)*", host) and not re.fullmatch(r"[\d.]+", host) else ""


def _host_of(value: str):
    """(host, scheme) of a URL-ish value or a bare host[:port]."""
    value = str(value).strip()
    if "://" in value:
        u = urlparse(value)
        return _norm_host(u.hostname or ""), u.scheme
    if re.fullmatch(r"[A-Za-z0-9.-]+(:\d+)?(/.*)?", value):
        return _norm_host(value.split("/")[0]), ""
    return "", ""


def parse_env_pairs(owner, pairs, repo, file, found: Finding, known: set, evidence_prefix=""):
    for key, value in pairs:
        if not (key.endswith(("_URL", "_URI", "_HOST", "_ADDR", "_ENDPOINT", "_DSN")) or "://" in str(value)):
            continue
        host, scheme = _host_of(value)
        if not host or host == owner:
            continue
        if host not in known and host not in found.services:
            if "." in str(value).split("://")[-1].split("/")[0].split(":")[0]:
                continue                            # an external FQDN (api.stripe.com) is not one of our services
        data = SCHEME_KIND.get(scheme)
        conf = "high" if (host in known and data) else "medium"
        found.add_service(host, kind=data)
        found.add_edge(owner, host, repo, file, f"{evidence_prefix}{key}", conf)


def parse_compose(text, repo, file, found: Finding):
    docs = [d for d in yaml.safe_load_all(text) if isinstance(d, dict)]
    for doc in docs:
        svcs = doc.get("services") or {}
        if not isinstance(svcs, dict):
            continue
        for name, spec in svcs.items():
            spec = spec or {}
            found.add_service(name, kind=guess_kind(name, str(spec.get("image", ""))), repo=repo, file=file)
    for doc in docs:
        svcs = doc.get("services") or {}
        known = set(svcs) if isinstance(svcs, dict) else set()
        for name, spec in (svcs.items() if isinstance(svcs, dict) else []):
            spec = spec or {}
            dep = spec.get("depends_on") or []
            for d in (dep.keys() if isinstance(dep, dict) else dep):
                found.add_edge(name, str(d), repo, file, "compose depends_on", "high")
            for l in spec.get("links") or []:
                found.add_edge(name, str(l).split(":")[0], repo, file, "compose links", "medium")
            env = spec.get("environment") or {}
            if isinstance(env, list):
                env = dict(e.split("=", 1) for e in env if isinstance(e, str) and "=" in e)
            parse_env_pairs(name, [(k, v) for k, v in env.items() if v is not None], repo, file, found, known, "env ")


def _k8s_docs(text):
    for d in yaml.safe_load_all(text):
        if isinstance(d, dict):
            yield d
            if d.get("kind") == "List":
                for it in d.get("items") or []:
                    if isinstance(it, dict):
                        yield it


def parse_k8s(text, repo, file, found: Finding):
    docs = list(_k8s_docs(text))
    svc_names = {d["metadata"]["name"] for d in docs if d.get("kind") == "Service" and d.get("metadata", {}).get("name")}
    for d in docs:
        kind, meta = d.get("kind"), d.get("metadata") or {}
        name = meta.get("name")
        if kind == "Service" and name:
            spec = d.get("spec") or {}
            found.add_service(name, kind=guess_kind(name), repo=repo, file=file)
            if spec.get("type") == "ExternalName" and spec.get("externalName"):
                host = _norm_host(spec["externalName"])
                if host:
                    found.add_edge(name, host, repo, file, "k8s Service ExternalName", "medium")
        elif kind in ("Deployment", "StatefulSet", "DaemonSet") and name:
            found.add_service(name, kind=guess_kind(name), repo=repo, file=file)
            pod = ((d.get("spec") or {}).get("template") or {}).get("spec") or {}
            for c in pod.get("containers") or []:
                pairs = [(e.get("name", ""), e.get("value")) for e in c.get("env") or [] if e.get("value") is not None]
                parse_env_pairs(name, pairs, repo, file, found, svc_names, "env ")
        elif kind == "Ingress":
            ing = name or "ingress"
            found.add_service(ing, kind="edge", repo=repo, file=file)
            spec = d.get("spec") or {}
            backends = []
            if (spec.get("defaultBackend") or {}).get("service"):
                backends.append(spec["defaultBackend"]["service"].get("name"))
            for rule in spec.get("rules") or []:
                for p in ((rule.get("http") or {}).get("paths") or []):
                    be = p.get("backend") or {}
                    backends.append((be.get("service") or {}).get("name") or be.get("serviceName"))
            for b in filter(None, backends):
                found.add_edge(ing, b, repo, file, "k8s Ingress", "high")


def _walk_values(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_values(v, path + (str(k),))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_values(v, path + (str(i),))
    else:
        yield path, node


def parse_helm_values(text, repo, file, found: Finding, owner=None):
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        return
    top = {k for k, v in doc.items() if isinstance(v, dict)}
    for path, value in _walk_values(doc):
        if value is None or not URLISH_KEY.search(path[-1]) or not isinstance(value, (str, int)):
            continue
        host, scheme = _host_of(value)
        if not host or host not in top | set(found.services):
            continue
        src = path[0] if path[0] in top and path[0] != host else (owner or repo)
        if src == host:
            continue
        found.add_edge(src, host, repo, file, "Helm values " + ".".join(path), "low")


def parse_env_file(text, repo, file, found: Finding, owner=None):
    owner = owner or repo
    parse_env_pairs(owner, ENV_LINE.findall(text), repo, file, found, set(found.services), "")


def parse_file(kind, text, repo, file, found: Finding, owner=None):
    found.files.append((repo, file, kind))
    try:
        if kind == "compose":
            parse_compose(text, repo, file, found)
        elif kind == "k8s":
            parse_k8s(text, repo, file, found)
        elif kind == "helm":
            parse_helm_values(text, repo, file, found, owner)
        elif kind == "env":
            parse_env_file(text, repo, file, found, owner)
    except yaml.YAMLError:
        found.files[-1] = (repo, file, kind + " (unparseable)")


def merge(found: Finding):
    """One proposal per (src, dst): strongest evidence wins; every source is kept for the reviewer."""
    best: dict = {}
    for e in found.edges:
        cur = best.get(e.key())
        src = {"repo": e.repo, "file": e.file, "evidence": e.evidence, "confidence": e.confidence}
        if cur is None:
            e.sources = [src]
            best[e.key()] = e
        else:
            cur.sources.append(src)
            if _RANK[e.confidence] > _RANK[cur.confidence]:
                cur.repo, cur.file, cur.evidence, cur.confidence = e.repo, e.file, e.evidence, e.confidence
    return sorted(best.values(), key=lambda e: (-_RANK[e.confidence], e.src, e.dst))


def source_group(evidence: str) -> str:
    if evidence.startswith("compose"):
        return "docker-compose"
    if evidence.startswith("k8s"):
        return "k8s manifests"
    if evidence.startswith("Helm"):
        return "Helm values"
    return "env vars"


def summarize(found: Finding, edges=None):
    edges = edges if edges is not None else merge(found)
    by_source = {}
    for e in edges:
        g = source_group(e.evidence)
        by_source[g] = by_source.get(g, 0) + 1
    kinds = {}
    for s in found.services.values():
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    return {"services": len(found.services), "dependencies": len(edges), "by_source": by_source, "by_kind": kinds,
            "repos": sorted({r for r, _, _ in found.files})}
