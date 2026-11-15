"""The single-write HTTP client, against a tiny local server (no HydraDB needed)."""
import json, socket, threading
import pytest
from ghostwalk.graph.fasthttp import FastClient


class Server:
    """Keep-alive HTTP/1.1 server. mode: 'length' | 'chunked' | 'close_after_first'. Records how many TCP reads each request needed."""
    def __init__(self, mode="length"):
        self.mode, self.requests, self.reads = mode, [], []
        self.sock = socket.socket(); self.sock.bind(("127.0.0.1", 0)); self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(c,), daemon=True).start()

    def serve(self, c):
        served = 0
        try:
            while True:
                buf, reads = b"", 0
                while b"\r\n\r\n" not in buf:
                    d = c.recv(65536)
                    if not d:
                        return
                    buf += d; reads += 1
                head, rest = buf.split(b"\r\n\r\n", 1)
                n = int([l for l in head.split(b"\r\n") if l.lower().startswith(b"content-length")][0].split(b":")[1])
                while len(rest) < n:
                    rest += c.recv(65536); reads += 1
                self.requests.append(json.loads(rest)); self.reads.append(reads)
                out = json.dumps({"rows": [[len(self.requests)]], "echo": json.loads(rest)["x"]}).encode()
                if self.mode == "chunked":
                    half = len(out) // 2
                    c.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + b"%x\r\n%s\r\n%x\r\n%s\r\n0\r\n\r\n" % (half, out[:half], len(out) - half, out[half:]))
                else:
                    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n" % len(out) + out)
                served += 1
                if self.mode == "close_after_first" and served == 1:
                    c.close()
                    return
        except OSError:
            return


def client(srv):
    return FastClient(f"http://127.0.0.1:{srv.port}", {"Authorization": "Bearer t"})


def test_headers_and_body_arrive_in_a_single_read_and_the_connection_is_reused():
    srv = Server("length")
    c = client(srv)
    for i in range(5):
        r = c.post(f"http://127.0.0.1:{srv.port}/v1/graphs/default/query", json={"x": i, "big": "y" * 2000})
        assert r.status_code == 200 and r.json()["echo"] == i
    assert srv.reads == [1] * 5                                   # one write per request: header and body never split
    assert [q["x"] for q in srv.requests] == list(range(5))
    c.close()


def test_chunked_responses_keep_the_connection_in_step():
    srv = Server("chunked")
    c = client(srv)
    got = [c.post(f"http://127.0.0.1:{srv.port}/q", json={"x": i}).json()["echo"] for i in range(6)]
    assert got == list(range(6))                                   # the trailing CRLF of each chunked body was consumed
    c.close()


def test_a_stale_kept_alive_connection_is_reopened_once():
    srv = Server("close_after_first")
    c = client(srv)
    url = f"http://127.0.0.1:{srv.port}/q"
    assert c.post(url, json={"x": 1}).json()["echo"] == 1
    assert c.post(url, json={"x": 2}).json()["echo"] == 2          # the server closed after the first response; the client reconnects
    c.close()


def test_each_thread_gets_its_own_connection():
    srv = Server("length")
    c = client(srv)
    out = []
    def work(i):
        out.append(c.post(f"http://127.0.0.1:{srv.port}/q", json={"x": i}).json()["echo"])
    ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(out) == list(range(8))


def test_https_is_not_handled_here():
    with pytest.raises(ValueError):
        FastClient("https://example.com")
