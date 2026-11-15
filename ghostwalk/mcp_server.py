"""`gw mcp`: the GhostWalk MCP server (stdio).

Local mode (default): reads the workspace saved by `gw` (GW_HOME, default ./.gw). Read-only: it never writes the graph.
Hosted mode: set GW_URL and GW_TOKEN and every tool call is forwarded to that GhostWalk server.
GhostWalk itself never calls an LLM. The assistant asks, the graph answers.
"""
from __future__ import annotations
import os, pathlib
import httpx
try:                                   # mcp 2.x renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:                    # mcp 1.x
    from mcp.server.fastmcp import FastMCP
from . import mcp_tools as tools
from .api.workspace import Workspace

INSTRUCTIONS = ("Ask GhostWalk why an alert storm happened. `why` ranks root causes from the dependency graph with confidence and a path; "
                "`path` explains a single route; `blast_radius` lists what depends on a service; `propose_edge` suggests a missing dependency "
                "for a human to review (it never changes the graph).")


def build_server() -> FastMCP:
    mcp = FastMCP("ghostwalk", instructions=INSTRUCTIONS)
    url, token = os.environ.get("GW_URL"), os.environ.get("GW_TOKEN")
    state = pathlib.Path(os.environ.get("GW_HOME", ".gw")) / "state.json"
    local: dict = {}

    def call(tool: str, **kw):
        if url:
            if not token:
                raise RuntimeError("GW_URL is set but GW_TOKEN is not")
            r = httpx.post(f"{url.rstrip('/')}/api/mcp/{tool}", json=kw, headers={"authorization": f"Bearer {token}"}, timeout=30)
            if r.status_code >= 400:
                raise RuntimeError(r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text)
            return r.json()
        if "ws" not in local:
            if not state.exists():
                raise RuntimeError("no GhostWalk map found. Run `gw map import ./your-repos` (or `gw demo`) first, or set GW_URL and GW_TOKEN.")
            local["ws"] = Workspace(state, demo=False)
        try:
            return getattr(tools, tool)(local["ws"], **kw)
        except tools.ToolError as e:
            raise RuntimeError(str(e))

    @mcp.tool()
    def why(alerts: list[dict | str]) -> dict:
        """Rank the likely root causes of an alert storm. `alerts` is a list of service names, or of {name, signal, t} objects
        (Alertmanager/Grafana payloads work too). Returns ranked roots with confidence, the path from the entry service, and an explanation."""
        return call("why", alerts=alerts)

    @mcp.tool()
    def path(root: str, service: str) -> dict:
        """Explain how `service` depends on `root`: the hops between them, and which were learned from postmortems."""
        return call("path", root=root, service=service)

    @mcp.tool()
    def blast_radius(service: str, hops: int = 3) -> dict:
        """Which services are affected if `service` fails, within `hops` dependency hops (default 3)."""
        return call("blast_radius", service=service, hops=hops)

    @mcp.tool()
    def why_edge(src: str, dst: str) -> dict:
        """Why does the graph say `src` depends on `dst`? If the edge was learned: the lesson, the postmortems that taught it and the incidents that confirmed it (needs the HydraDB store)."""
        return call("why_edge", src=src, dst=dst)

    @mcp.tool()
    def lesson_impact(lesson_id: int) -> dict:
        """Which services and past incidents have paths that use this learned edge (a lesson id from why_edge)."""
        return call("lesson_impact", lesson_id=lesson_id)

    @mcp.tool()
    def propose_edge(src: str, dst: str, incident_id: str = "", reason: str = "") -> dict:
        """Suggest a lesson: `src` depends on `dst`. Creates a PENDING proposal a human approves in GhostWalk; it never writes the graph."""
        return call("propose_edge", src=src, dst=dst, incident_id=incident_id or None, reason=reason)

    return mcp


def main():
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
