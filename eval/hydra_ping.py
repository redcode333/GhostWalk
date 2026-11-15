"""Where do HydraDB's ~48 ms per request go? Sequential request timing across transports, with the server's own execution time from /metrics.

    python eval/hydra_ping.py [--n 200] [--label host] [--out file.json]
    docker run --rm --network ghostwalk_default -v <repo>:/app -w /app python:3.12-slim sh -c \\
        "pip install -q 'httpx[http2]' neo4j && python eval/hydra_ping.py --url http://hydradb:8443 --admin http://hydradb:9090 --bolt bolt://hydradb:7687 --label docker-network"

Standalone (httpx + optional neo4j). For every transport and every query: 20 warm-up requests, then N timed ones, one at a time.
Server-side time: HydraDB's response carries no timing field, so /metrics histograms are read before and after each block and the mean of
graph_client_operation_read_duration_seconds is reported (the server's own execution of the query, not the network).
"""
from __future__ import annotations
import argparse, http.client, json, re, socket, statistics, sys, time, urllib.parse
import httpx

TOKEN = "local-development-token-32-bytes"
BASE = 9_100_000_000
N_NODES = 20


def pct(xs):
    s = sorted(xs)
    return {"p50": s[len(s) // 2], "p95": s[int(len(s) * 0.95) - 1], "min": s[0], "max": s[-1], "mean": statistics.fmean(s), "n": len(s)}


QUERIES = {
    "trivial_read": ("MATCH (n:PingNode) RETURN count(*) AS c", {}),
    "one_hop": ("MATCH (a:PingNode {id: $s})-[:PING]->(b) RETURN b.id AS id", {"s": BASE}),
    "sp_3hops": ("CALL algo.SPpaths({sourceNode: $s, targetNode: $t, relTypes: ['PING'], relDirection: 'outgoing', maxLen: 3, weightProp: 'cost', costProp: 'cost', pathCount: 1}) "
                 "YIELD path, pathCost RETURN path, pathCost", {"s": BASE, "t": BASE + 4}),
    "sp_5hops": ("CALL algo.SPpaths({sourceNode: $s, targetNode: $t, relTypes: ['PING'], relDirection: 'outgoing', maxLen: 5, weightProp: 'cost', costProp: 'cost', pathCount: 1}) "
                 "YIELD path, pathCost RETURN path, pathCost", {"s": BASE, "t": BASE + 8}),
}


def body(query, params):
    return {"cell_id": "cell-0", "query": query, "parameters": params, "page_size": 4096}


class Metrics:
    """Mean of HydraDB's own read-operation histogram between two scrapes."""
    PAT = re.compile(r"^(graph_client_operation_read_duration_seconds|graph_client_operation_write_duration_seconds)_(sum|count)(?:\{[^}]*\})?\s+([0-9.eE+-]+)", re.M)

    def __init__(self, admin):
        self.admin = admin

    def scrape(self):
        t = httpx.get(self.admin + "/metrics", timeout=10).text
        out = {}
        for name, kind, val in self.PAT.findall(t):
            out[(name, kind)] = out.get((name, kind), 0.0) + float(val)
        return out

    @staticmethod
    def mean_ms(a, b, which="read"):
        k = f"graph_client_operation_{which}_duration_seconds"
        dc = b.get((k, "count"), 0) - a.get((k, "count"), 0)
        ds = b.get((k, "sum"), 0) - a.get((k, "sum"), 0)
        return (ds / dc * 1000, dc) if dc else (None, 0)


# ---- transports: each is a callable(query, params) -> rows --------------------------------------------------------------------
NODELAY = [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]


class HttpxKeepalive:
    name = "httpx keep-alive"
    def __init__(self, url, http2=False, nodelay=False):
        self.url = f"{url}/v1/graphs/default/query"
        tr = httpx.HTTPTransport(http1=not http2, http2=http2, socket_options=NODELAY if nodelay else None)
        self.c = httpx.Client(transport=tr, timeout=60, headers={"Authorization": f"Bearer {TOKEN}", "X-Graph-Namespace": "default"})
        self.name = ("httpx HTTP/2 (prior knowledge)" if http2 else "httpx keep-alive") + (" + TCP_NODELAY" if nodelay else "")
    def __call__(self, q, p):
        r = self.c.post(self.url, json=body(q, p))
        return r.json()["rows"]
    def close(self): self.c.close()


class HttpxNewConn:
    name = "httpx new connection per request"
    def __init__(self, url):
        self.url = f"{url}/v1/graphs/default/query"
    def __call__(self, q, p):
        with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {TOKEN}", "X-Graph-Namespace": "default"}) as c:
            return c.post(self.url, json=body(q, p)).json()["rows"]
    def close(self): pass


class HttpClient:
    """stdlib http.client: no pooling layer, no extras. keepalive=True reuses one TCP connection."""
    def __init__(self, url, keepalive=True, nodelay=False):
        u = urllib.parse.urlparse(url)
        self.host, self.port, self.keep, self.nodelay = u.hostname, u.port, keepalive, nodelay
        self.name = ("http.client keep-alive" if keepalive else "http.client new connection") + (" + TCP_NODELAY" if nodelay else "")
        self.conn = None
    def _c(self):
        if self.conn is None or not self.keep:
            if self.conn: self.conn.close()
            self.conn = http.client.HTTPConnection(self.host, self.port, timeout=60)
            if self.nodelay:
                self.conn.connect()
                self.conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return self.conn
    def __call__(self, q, p):
        c = self._c()
        c.request("POST", "/v1/graphs/default/query", json.dumps(body(q, p)), {"Authorization": f"Bearer {TOKEN}", "X-Graph-Namespace": "default", "Content-Type": "application/json"})
        return json.loads(c.getresponse().read())["rows"]
    def close(self):
        if self.conn: self.conn.close()


class RawSocket:
    """HTTP/1.1 over a bare socket. One write for headers+body, TCP_NODELAY configurable, and the first/last byte times and the number of
    reads are recorded, to see whether the response arrives in two writes ~40 ms apart (the Nagle / delayed-ACK signature)."""
    def __init__(self, url, nodelay=True):
        u = urllib.parse.urlparse(url)
        self.addr, self.nodelay = (u.hostname, u.port), nodelay
        self.name = f"raw socket, TCP_NODELAY {'on' if nodelay else 'off'}"
        self.s = None
        self.first, self.last, self.chunks, self.gaps = [], [], [], []
    def _connect(self):
        self.s = socket.create_connection(self.addr, timeout=60)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1 if self.nodelay else 0)
    def __call__(self, q, p):
        if self.s is None:
            self._connect()
        payload = json.dumps(body(q, p)).encode()
        req = (f"POST /v1/graphs/default/query HTTP/1.1\r\nHost: {self.addr[0]}:{self.addr[1]}\r\nAuthorization: Bearer {TOKEN}\r\nX-Graph-Namespace: default\r\n"
               f"Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n").encode() + payload
        t0 = time.perf_counter()
        self.s.sendall(req)
        buf, need, hdr_end, n, t_prev, gap = b"", None, None, 0, None, 0.0
        while True:
            chunk = self.s.recv(65536)
            now = time.perf_counter()
            if not chunk:
                raise ConnectionError("closed")
            if n == 0:
                self.first.append((now - t0) * 1000)
            elif t_prev is not None:
                gap = max(gap, (now - t_prev) * 1000)
            n += 1
            t_prev = now
            buf += chunk
            if hdr_end is None and b"\r\n\r\n" in buf:
                hdr_end = buf.index(b"\r\n\r\n") + 4
                m = re.search(rb"(?i)content-length:\s*(\d+)", buf[:hdr_end])
                chunked = b"transfer-encoding: chunked" in buf[:hdr_end].lower()
                need = int(m.group(1)) if m else None
            if hdr_end is not None:
                if need is not None and len(buf) - hdr_end >= need:
                    break
                if chunked and buf.endswith(b"0\r\n\r\n"):
                    break
        self.last.append((time.perf_counter() - t0) * 1000)
        self.chunks.append(n)
        self.gaps.append(gap)
        raw = buf[hdr_end:]
        if chunked:
            parts, i = [], 0
            while True:
                j = raw.index(b"\r\n", i); size = int(raw[i:j], 16)
                if size == 0: break
                parts.append(raw[j + 2:j + 2 + size]); i = j + 2 + size + 2
            raw = b"".join(parts)
        return json.loads(raw)["rows"]
    def close(self):
        if self.s: self.s.close()


class Bolt:
    name = "Bolt (neo4j driver)"
    def __init__(self, uri):
        from neo4j import GraphDatabase
        self.d = GraphDatabase.driver(uri, auth=("neo4j", TOKEN))
        self.d.verify_connectivity()
    def __call__(self, q, p):
        with self.d.session(database="default") as s:
            return [list(r.values()) for r in s.run(q, **p)]
    def close(self): self.d.close()


def setup(url):
    c = httpx.Client(timeout=60, headers={"Authorization": f"Bearer {TOKEN}", "X-Graph-Namespace": "default"})
    api = f"{url}/v1/graphs/default/query"
    def q(query, **params):
        r = c.post(api, json={"cell_id": "cell-0", "query": query, "parameters": params}).json()
        if "error" in r:
            raise RuntimeError(r["error"])
    q("UNWIND $rows AS row MATCH (n {id: row.id}) DETACH DELETE n", rows=[{"id": BASE + i} for i in range(N_NODES)])
    edges = [(i, i + 1) for i in range(N_NODES - 1)] + [(i, i + 2) for i in range(0, N_NODES - 2, 3)]
    for k, (u, v) in enumerate(edges):
        q("MERGE (a:PingNode {id: $u})-[:PING {w: $w, cost: $c}]->(b:PingNode {id: $v})", u=BASE + u, v=BASE + v, w=0.7, c=0.3567 + 0.01 * (k % 5))
    c.close()
    return len(edges)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8443")
    ap.add_argument("--admin", default="http://127.0.0.1:9090")
    ap.add_argument("--bolt", default="bolt://127.0.0.1:7687")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--label", default="host")
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", nargs="*", default=None, help="substring filter on transport names")
    ap.add_argument("--skip-setup", action="store_true")
    a = ap.parse_args()
    m = Metrics(a.admin)
    edges = None if a.skip_setup else setup(a.url)
    transports = [lambda: HttpxKeepalive(a.url), lambda: HttpxKeepalive(a.url, nodelay=True), lambda: HttpClient(a.url, True), lambda: HttpClient(a.url, True, nodelay=True),
                  lambda: HttpClient(a.url, False), lambda: RawSocket(a.url, True), lambda: RawSocket(a.url, False),
                  lambda: HttpxKeepalive(a.url, http2=True), lambda: HttpxKeepalive(a.url, http2=True, nodelay=True), lambda: Bolt(a.bolt)]
    results = {"label": a.label, "n": a.n, "url": a.url, "graph_edges": edges, "transports": {}}
    # the floor: a request that runs no query at all
    with httpx.Client(timeout=10) as c:
        ts = []
        for i in range(a.n + 20):
            t0 = time.perf_counter(); c.get(a.url + "/healthz"); ts.append((time.perf_counter() - t0) * 1000)
        results["healthz_floor_ms"] = pct(ts[20:])
    for make in transports:
        try:
            t = make()
        except Exception as e:
            nm = getattr(make, "__name__", "?")
            results["transports"][f"(unavailable) {nm}"] = {"error": str(e)[:200]}
            print(f"  ! transport unavailable: {str(e)[:120]}", flush=True)
            continue
        if a.only and not any(s.lower() in t.name.lower() for s in a.only):
            t.close(); continue
        row = {}
        for qn, (query, params) in QUERIES.items():
            try:
                for _ in range(20):
                    t(query, params)
                before = m.scrape()
                ms = []
                for _ in range(a.n):
                    t0 = time.perf_counter(); rows = t(query, params); ms.append((time.perf_counter() - t0) * 1000)
                after = m.scrape()
            except Exception as e:
                row[qn] = {"error": str(e)[:200]}
                continue
            srv, cnt = m.mean_ms(before, after)
            row[qn] = {"client_ms": pct(ms), "server_read_op_mean_ms": srv, "server_ops_counted": cnt, "rows": len(rows)}
            if isinstance(t, RawSocket) and t.first:
                tail = slice(-a.n, None)
                row[qn]["first_byte_ms_p50"] = statistics.median(t.first[tail])
                row[qn]["last_byte_ms_p50"] = statistics.median(t.last[tail])
                row[qn]["reads_per_response_p50"] = statistics.median(t.chunks[tail])
                row[qn]["max_gap_between_reads_ms_p95"] = sorted(t.gaps[tail])[int(a.n * 0.95) - 1]
        results["transports"][t.name] = row
        t.close()
        line = "  ".join(f"{qn} {row[qn]['client_ms']['p50']:6.1f}/{row[qn]['client_ms']['p95']:6.1f}" if "client_ms" in row.get(qn, {}) else f"{qn} n/a" for qn in QUERIES)
        print(f"{a.label:15s} {t.name:42s} {line}", flush=True)
    srv = {qn: next((v[qn]["server_read_op_mean_ms"] for v in results["transports"].values() if v.get(qn, {}).get("server_read_op_mean_ms") is not None), None) for qn in QUERIES}
    print("server-side read op mean (ms):", {k: (round(v, 3) if v is not None else None) for k, v in srv.items()})
    print(f"/healthz (no query) p50 {results['healthz_floor_ms']['p50']:.1f} ms p95 {results['healthz_floor_ms']['p95']:.1f} ms")
    if a.out:
        open(a.out, "w", encoding="utf8").write(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
