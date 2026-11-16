"""Renders the high-level architecture diagram: docs/architecture.png and docs/architecture.svg.

Uses mingrammer/diagrams (Graphviz) with the providers' own icons. HydraDB is a Custom node with its mark (docs/assets/hydradb.png);
Clerk has no icon in the library and is a plain node.

    pip install diagrams            # and Graphviz (apt install graphviz, brew install graphviz)
    python scripts/render_architecture.py

Without Graphviz installed locally, run it in a container:
    docker run --rm -v "$PWD":/w -w /w python:3.12-slim sh -c "apt-get update -qq && apt-get install -y -qq graphviz >/dev/null && pip install -q diagrams && python scripts/render_architecture.py"
"""
from __future__ import annotations
import pathlib

from diagrams import Cluster, Diagram, Edge, Node
from diagrams.aws.compute import EC2
from diagrams.custom import Custom
from diagrams.generic.storage import Storage
from diagrams.onprem.client import Client
from diagrams.onprem.container import Docker
from diagrams.onprem.network import Caddy
from diagrams.onprem.vcs import Github
from diagrams.programming.framework import FastAPI, React, Vercel

ROOT = pathlib.Path(__file__).resolve().parent.parent
HYDRA = str(ROOT / "docs" / "assets" / "hydradb.png")
NL = "\n"

GRAPH = {"bgcolor": "white", "pad": "0.4", "nodesep": "0.6", "ranksep": "1.1", "fontname": "Helvetica", "fontsize": "15", "dpi": "150", "splines": "spline", "newrank": "true"}
NODE = {"fontname": "Helvetica", "fontsize": "13"}
EDGE = {"fontname": "Helvetica", "fontsize": "12", "color": "#5B5870", "fontcolor": "#2B2840"}
CLUSTER = {"fontname": "Helvetica", "fontsize": "14", "style": "rounded", "color": "#B9B4D0", "bgcolor": "#FAF9FD", "margin": "16"}


def rank(d, *nodes):
    """Put nodes on one row (Graphviz rank=same), so a top-to-bottom layout stays wide."""
    d.dot.body.append("{rank=same; " + "; ".join(chr(34) + n._id + chr(34) for n in nodes) + "}")


def build(fmt: str):
    with Diagram("", filename=str(ROOT / "docs" / "architecture"), outformat=fmt, show=False, direction="TB", graph_attr=GRAPH, node_attr=NODE, edge_attr=EDGE) as d:
        with Cluster("Alert sources", graph_attr=CLUSTER):
            webhooks = Node(f"JSON alert webhooks{NL}common normalized payloads", shape="box", style="rounded,filled", fillcolor="#F3F0FF", color="#6A4BFF", width="2.3", height="1.1")
            gw = Client(f"gw CLI and{NL}MCP clients")
        gh = Github(f"GitHub{NL}postmortem issues")

        with Cluster("Frontend (Vercel)", graph_attr=CLUSTER):
            web = React("React web app")
            vercel = Vercel("Vercel")
        clerk = Node(f"Clerk{NL}sign-in and sessions", shape="box", style="rounded,filled", fillcolor="#F3F0FF", color="#6A4BFF", width="2.3", height="1.1")

        with Cluster("AWS EC2  -  Docker Compose", graph_attr=CLUSTER):
            host = EC2("EC2 host")
            compose = Docker("Docker Compose")
            caddy = Caddy(f"Caddy{NL}TLS and proxy")
            api = FastAPI(f"GhostWalk API{NL}engine, learner,{NL}write-through cache")
            hydra = Custom(f"HydraDB{NL}graph and memory", HYDRA)
            store = Storage(f"MinIO{NL}object storage")

        rank(d, webhooks, gw)
        rank(d, gh, web, vercel, clerk)
        rank(d, host, compose, caddy, api, hydra, store)

        webhooks >> Edge(label="JSON alerts") >> caddy
        gw >> Edge(label="alerts, why") >> caddy
        gh >> Edge(label="postmortems", style="dashed") >> caddy
        web >> Edge(label="verdicts, paths", color="#6A4BFF") >> caddy
        clerk >> Edge(label="sessions", style="dashed") >> web
        vercel >> Edge(style="invis") >> web
        host >> Edge(style="invis") >> compose >> Edge(style="invis") >> caddy
        caddy >> Edge(label="HTTPS") >> api
        api >> Edge(label="paths, lessons", color="#6A4BFF") >> hydra
        hydra >> Edge(label="objects") >> store


if __name__ == "__main__":
    for f in ("png", "svg"):
        build(f)
    print("wrote docs/architecture.png and docs/architecture.svg")
