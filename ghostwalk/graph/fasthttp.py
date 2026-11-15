"""A minimal persistent HTTP/1.1 client that sends every request in ONE write.

Why it exists: against a HydraDB published by Docker Desktop on Windows, httpx and http.client (which write the headers and the body separately)
took ~45 ms per request, flat for every query. The same clients inside the docker network took ~0.7 ms, and a client that writes headers+body in one
segment took ~0.4 ms even through the published port (eval/hydra_ping.py has the measurements). Client-side TCP_NODELAY did not help; the single
write does. This class is that single write, on a kept-alive connection, with a connection per thread.

Only what the adapter needs: POST with a JSON body, Content-Length or chunked responses, keep-alive, one transparent retry when a REUSED connection turns
out to have been closed (and nothing had come back). https:// is not handled here (the adapter falls back to httpx for it).
"""
from __future__ import annotations
import json, re, socket, threading, urllib.parse

_LEN = re.compile(rb"(?i)\r\ncontent-length:\s*(\d+)")


class Response:
    def __init__(self, status, body):
        self.status_code, self.content = status, body

    @property
    def text(self):
        return self.content.decode("utf8", "replace")

    def json(self):
        return json.loads(self.content)


class FastClient:
    def __init__(self, base_url: str, headers: dict | None = None, timeout: float = 60.0):
        u = urllib.parse.urlparse(base_url)
        if u.scheme != "http":
            raise ValueError("FastClient speaks plain http only")
        self.host, self.port, self.timeout = u.hostname, u.port or 80, timeout
        self.headers = dict(headers or {})
        self._local = threading.local()

    # ---- connection per thread ----------------------------------------------------------------
    def _sock(self):
        s = getattr(self._local, "sock", None)
        if s is None:
            s = socket.create_connection((self.host, self.port), timeout=self.timeout)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._local.sock = s
            self._local.fresh = True
        return s

    def _drop(self):
        s = getattr(self._local, "sock", None)
        if s is not None:
            try:
                s.close()
            finally:
                self._local.sock = None

    def close(self):
        self._drop()

    # ---- request ------------------------------------------------------------------------------
    def post(self, url, json=None, **_):             # noqa: A002  (mirrors httpx's signature for the one call the adapter makes)
        path = urllib.parse.urlparse(url).path or "/"
        payload = __import__("json").dumps(json).encode()
        head = [f"POST {path} HTTP/1.1", f"Host: {self.host}:{self.port}", "Content-Type: application/json", f"Content-Length: {len(payload)}", "Connection: keep-alive"]
        head += [f"{k}: {v}" for k, v in self.headers.items()]
        req = ("\r\n".join(head) + "\r\n\r\n").encode() + payload           # headers and body in a single write
        for attempt in (0, 1):
            s = self._sock()
            reused = not self._local.fresh
            self._local.fresh = False
            try:
                s.sendall(req)
                return self._read(s)
            except (ConnectionError, socket.timeout, BrokenPipeError, OSError) as e:
                self._drop()
                if attempt == 0 and reused and not isinstance(e, socket.timeout) and getattr(e, "_got_bytes", False) is False:
                    continue                                                  # the kept-alive connection had been closed: reconnect once
                raise

    def _read(self, s) -> Response:
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                err = ConnectionError("connection closed before a response")
                err._got_bytes = bool(buf)
                raise err
            buf += chunk
        i = buf.index(b"\r\n\r\n") + 4
        head, rest = buf[:i], buf[i:]
        status = int(head.split(b" ", 2)[1])
        low = head.lower()
        if b"transfer-encoding: chunked" in low:
            body = self._chunked(s, rest)
        else:
            m = _LEN.search(b"\r\n" + head)
            need = int(m.group(1)) if m else 0
            while len(rest) < need:
                chunk = s.recv(65536)
                if not chunk:
                    raise ConnectionError("connection closed mid-body")
                rest += chunk
            body = rest[:need]
        if b"connection: close" in low:
            self._drop()
        return Response(status, body)

    @staticmethod
    def _chunked(s, buf: bytes) -> bytes:
        out = []
        while True:
            while b"\r\n" not in buf:
                c = s.recv(65536)
                if not c:
                    raise ConnectionError("closed mid-chunk")
                buf += c
            line, buf = buf.split(b"\r\n", 1)
            size = int(line.split(b";")[0], 16)
            while len(buf) < size + 2:
                c = s.recv(65536)
                if not c:
                    raise ConnectionError("closed mid-chunk")
                buf += c
            if size == 0:                                     # consume the final CRLF so a kept-alive connection stays in step
                while len(buf) < 2:
                    c = s.recv(65536)
                    if not c:
                        break
                    buf += c
                return b"".join(out)
            out.append(buf[:size])
            buf = buf[size + 2:]
