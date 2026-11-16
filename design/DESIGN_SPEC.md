# GhostWalk web design spec (draft 4)

Source of truth: the `.dc.html` files in this folder (one per screen). They are self-contained HTML; open any in a browser to see the screen. Rebuild them as React + Vite + TS + Tailwind components. Copy the text exactly; tokens and behaviour below.

## Screens
| File | Route | Notes |
|---|---|---|
| Main.dc.html | `/` | Landing page. Light by default, dark toggle in the navbar |
| SignUp.dc.html | `/signup` | Clerk `<SignUp/>` themed to match (see AUTH below) |
| SignIn.dc.html | `/signin` | Clerk `<SignIn/>` themed to match |
| Incidents.dc.html | `/app/incidents` | Dashboard is always dark |
| Incident.dc.html | `/app/incidents/:id` | |
| Learn.dc.html | `/app/learn/:id` | |
| Map.dc.html | `/app/map` | |
| Proof.dc.html | `/app/proof` | Reads results.json |
| Settings.dc.html | `/app/settings` | |
| Onboarding.dc.html | `/app/onboarding` | GitHub App → proposed map from compose/k8s/env vars → alert webhook → postmortem issue form |
| CLI.dc.html | docs + README image | How `gw` output should look: map, why, learn, eval |

## Tokens
Light (marketing default) / Dark (`.dark`, toggled from the navbar, saved in localStorage; the app always uses dark)

| token | light | dark |
|---|---|---|
| --bg | #F4F2EC | #09090E |
| --surface | #FFFFFF | #13131B |
| --surface-2 | #FAF9F6 | #0F0F16 |
| --muted | #EFEDE7 | #1D1D27 |
| --ink (text) | #0D0D10 | #F6F5F1 |
| --text-2 | #2A2A30 | #DAD9E2 |
| --text-3 | #55555C | #A6A5B1 |
| --text-4 | #66666E | #8F8E9A |
| --accent (violet) | #6A4BFF | #8E76FF |
| --accent-text | #5536F0 | #AC9BFF |
| --amber (alerting only) | #D99614 | #F5B83F |
| lines | rgba(13,13,16,.08) | rgba(255,255,255,.08) |

Brand rule: 3 colours only. Ink = primary (buttons, logo ghost). Violet = only what GhostWalk sees that you don't (root cause, learned edges). Amber = alerting status. No orange anywhere (that is HydraDB's brand).

Graph tier colours (graph elements only): edge #3D7DFF, service #12B5A0, data #E2549A, infra #7FB800. Alerting = amber ring, root = violet fill, learned edge = violet dashed.

Type: Geist (UI), Geist Mono (ids, numbers, code; tabular-nums). Logo 66×38 px in the nav; wordmark "ghost" + "walk" (walk in violet), Geist Mono 27px semibold.

Buttons:
- primary: ink vertical gradient (#3A3A44 → #18181D → #0D0D10), 1px #000 border, inset top highlight rgba(255,255,255,.28), violet soft drop shadow; inverted in dark (white → #D9D6CD, ink text). Moves down 1px when pressed.
- glass: white 88%→58% gradient, 1px line border, inset white highlight, backdrop blur 12px.
- Fully rounded on marketing pages, 12px radius in the app. Focus ring 2px violet.

## Landing sections (in order)
1. Header: logo · LiquidNavbar (`components/ui/liquid-glass-navbar.tsx`, tone follows theme; items Product, Customers, How it works, FAQ, GitHub; lucide icons) · theme toggle · Sign in · Get started.
2. Hero, centred: "Open source · Root cause analysis on HydraDB" pill, H1 "The outage is never where the pager says." (84px), sub, Get started + Watch a live outage, and the fine print "Free and open source · MIT licensed · docker compose up". Below that, the globe as a horizon (cropped container 500px high, bottom fade to --bg).
3. Globe (cobe, reusing the engine from the testimonial-globe component; no testimonials, no portraits): tours the outages in `src/data/outages.ts` (below). Every 4.8s, ease phi to −lng and tilt to lat−0.45 rad. A glass snippet card follows the projected pin. Amber arcs from the active pin to 2 others; a violet dashed arc to a third. Company chips below the globe are clickable and reset the timer. Caption: "Real outages from public postmortems. Each one spread through a dependency."
4. Story: Cloudflare, 18 Nov 2025 (real; link https://blog.cloudflare.com/18-november-2025-outage/). Left card: the postmortem timeline in UTC (11:05 ClickHouse change, 11:20 5xx, DDoS suspected, Turnstile/login/KV/Access errors, 14:30 core recovered, 17:06 all restored) and 3h 10m core / 5h 46m total. Right card, labelled illustrative: how GhostWalk walks the 5 alerts → core proxy ⇢ bot feature file → ClickHouse.
5. Bento (6 tiles): Walks the graph live (tier-coloured graph + legend), Explains itself, Learns from postmortems, Proves it gets better, Plugs into your alerts, No LLM in the hot path, Open source core.
6. "From clone to first verdict in three commands": steps on the left; on the right a terminal whose lines fade in and whose bottom is masked to transparent. Proof stat strip below it (reads results.json).
7. FAQ (7 questions, including "Is it free?") · final CTA ("Free and open source. MIT licensed." with the Get started, Watch a live outage and GitHub buttons) · footer.

## outages.ts (verify every line against its postmortem and add a `source` URL before shipping)
| company | when | lat,lng | hidden dependency |
|---|---|---|---|
| Cloudflare | Nov 2025 | 37.77,-122.42 | proxy ⇢ feature file |
| AWS us-east-1 | Oct 2025 | 39.04,-77.49 | services ⇢ DynamoDB DNS |
| CrowdStrike | Jul 2024 | 30.27,-97.74 | Windows boot ⇢ sensor update |
| Rogers | Jul 2022 | 43.65,-79.38 | core network ⇢ routing filter |
| OVHcloud | Mar 2021 | 48.58,7.75 | sites ⇢ one data center |
| Tokyo Stock Exchange | Oct 2020 | 35.68,139.69 | trading ⇢ storage failover |
| Atlassian | Apr 2022 | -33.87,151.21 | customer sites ⇢ cleanup script |
One-line "what happened" text: copy from Main.dc.html (`snipsData()`).

## Proof strip values (from results.json, never hard-coded)
- top-1 gain over the best baseline = ghostwalk AC@1 − max(baseline AC@1), with paired CI
- gap closed = (ghostwalk − learning_off) / (oracle − learning_off)
- p95 time to verdict
- store swap delta (shown only once the real store-swap run exists; otherwise hide the tile)

## AUTH
`AUTH_MODE=none` (default in docker compose): no sign-in, opens the demo workspace. `AUTH_MODE=clerk`: Clerk, appearance colorPrimary = --ink, colorBackground = --surface, borderRadius 12px, Geist.

## Motion
Every animation is off under prefers-reduced-motion. The globe pauses when off-screen or in a hidden tab.
