// Real outages from public postmortems. `source` is the postmortem or analysis behind the line; `check` records how it was verified.
// `cost` is an analyst estimate (never a company figure) and always names who estimated it.
export type Outage = {
  company: string; when: string; lat: number; lng: number; what: string; edge: string
  cost?: string; costSource?: string; source: string; check: string
}

export const OUTAGES: Outage[] = [
  { company: "Cloudflare", when: "Nov 2025", lat: 37.77, lng: -122.42, edge: "proxy ⇢ feature file",
    what: "A generated config file doubled in size. Proxy services that read it began failing across the network.",
    cost: "est. $250M–$300M (Forrester)", costSource: "https://www.forrester.com/blogs/cloudflares-outage-another-wake-up-call-for-cloud-resilience",
    source: "https://blog.cloudflare.com/18-november-2025-outage/", check: "verified against the postmortem; Forrester's range is tied to a 3h20m outage window" },
  { company: "AWS us-east-1", when: "Oct 2025", lat: 39.04, lng: -77.49, edge: "services ⇢ DynamoDB DNS",
    what: "A DNS fault in DynamoDB's endpoint automation spread to the many services built on DynamoDB.",
    cost: "est. $500M–$650M for US companies (Parametrix)", costSource: "https://insurance-edge.net/2025/10/30/parametrix-estimates-aws-outage-costs/",
    source: "https://aws.amazon.com/message/101925/", check: "verified against the AWS event summary (race condition in DNS automation); the estimate is financial loss, not insured loss" },
  { company: "CrowdStrike", when: "Jul 2024", lat: 30.27, lng: -97.74, edge: "Windows boot ⇢ sensor update",
    what: "A faulty sensor content update crashed about 8.5 million Windows machines at boot.",
    cost: "est. $5.4B for the Fortune 500 (Parametrix)", costSource: "https://parametrixinsurance.com/in-the-news/crowdstrike-to-cost-fortune-500-5-4-billion-insured-loss-range-of-540-million-to-1-08-billion",
    source: "https://www.crowdstrike.com/en-us/blog/channel-file-291-rca-available/",
    check: "cause matches CrowdStrike's RCA (Channel File 291 content mismatch). The 8.5 million count is Microsoft's estimate, not in the RCA; the $5.4B is direct losses and excludes Microsoft" },
  { company: "Rogers", when: "Jul 2022", lat: 43.65, lng: -79.38, edge: "core network ⇢ routing filter",
    what: "A maintenance change removed a routing filter. Mobile and internet went down across Canada.",
    source: "https://crtc.gc.ca/eng/publications/reports/xona2024.htm",
    check: "the routing-filter detail is Rogers' own account; the CRTC-commissioned review words it as a router configuration error" },
  { company: "OVHcloud", when: "Mar 2021", lat: 48.58, lng: 7.75, edge: "sites ⇢ one data center",
    what: "A fire destroyed a Strasbourg data center. Sites with no copy elsewhere went offline.",
    source: "https://www.datacenterknowledge.com/uptime/fire-has-destroyed-ovh-s-strasbourg-data-center-sbg2-",
    check: "event confirmed by press coverage; no full official postmortem was retrieved" },
  { company: "Tokyo Stock Exchange", when: "Oct 2020", lat: 35.68, lng: 139.69, edge: "trading ⇢ storage failover",
    what: "A storage device failed and automatic failover didn't take over. Trading halted for a full day.",
    source: "https://blocksandfiles.com/2020/10/02/tokyo-stock-exchange-outage-storage-fault/",
    check: "matches TSE's report (memory module failure, automatic switchover did not work)" },
  { company: "Atlassian", when: "Apr 2022", lat: -33.87, lng: 151.21, edge: "customer sites ⇢ cleanup script",
    what: "A maintenance script deleted hundreds of customers' sites. Some stayed down for two weeks.",
    source: "https://www.atlassian.com/engineering/post-incident-review-april-2022-outage",
    check: "verified: 883 sites, 775 customers, longest outages up to 14 days" },
]

// Cloudflare cost model for the slider: the Forrester midpoint spread over the core-impact minutes. Back-of-envelope, shown as such.
export const CLOUDFLARE = { lowM: 250, highM: 300, midM: 275, coreMinutes: 190, forrester: OUTAGES[0].costSource!, techinformed: "https://techinformed.com/cloudflare-outage-exposes-the-hidden-fragility-of-the-internet/" }
export const savedM = (foundInMinutes: number) => (CLOUDFLARE.midM / CLOUDFLARE.coreMinutes) * (CLOUDFLARE.coreMinutes - foundInMinutes)
