# Reference

Generated from `docs/templates/REFERENCE.tpl.md`. The README has the quickstart; this has every setting, command and tool.

## Configuration

Copy `.env.example` to `.env`. Secrets are never committed.

{{env_table}}

## CLI

{{cli_reference}}

## The six MCP tools

| tool | arguments | what it does |
|---|---|---|
| `why` | `alerts` (service names, or `{name, signal, t}`; Alertmanager and Grafana payloads work) | ranks root causes with a confidence, the path and an explanation |
| `path` | `root`, `service` | explains how `service` depends on `root`, hop by hop, and which hops were learned |
| `blast_radius` | `service`, `hops` | what is affected if `service` fails |
| `why_edge` | `src`, `dst` | the lesson behind a learned edge, the postmortems that taught it and the incidents that confirmed it (HydraDB store) |
| `lesson_impact` | `lesson_id` | the services and past incidents whose paths use a learned edge |
| `propose_edge` | `src`, `dst`, `incident_id`, `reason` | suggests a lesson as a pending proposal; a person approves it, nothing is written |

GhostWalk never calls an LLM. The assistant asks and the graph answers.
