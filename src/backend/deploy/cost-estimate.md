# Scene hackathon deploy: cost estimate (Cloud SQL + Cloud Run + Secret Manager)

Workflow: scene-cloudsql-deploy. Worker 5 (cost estimator). Date: Sun Oct 25, 2026.

## Headline answer

All figures are ESTIMATES from public pricing pages, not quotes. Region and exact tier change the numbers.

Recommended config: Cloud SQL for PostgreSQL, non-HA, db-f1-micro, 10 GB SSD, backups off, no public IP (private IP / Cloud SQL connector from Cloud Run), Cloud Run scale-to-zero with no minimum instances, 2 secrets in Secret Manager.

| Scenario | Estimated total |
|---|---|
| Demo weekend, 48 hours running, db-f1-micro | **about $0.61, budget $1** (Cloud Run $0, Secret Manager $0, other $0-0.20) |
| Demo weekend, 72 hours running (setup Fri to teardown Sun), db-f1-micro | **about $0.93, budget $1-1.50** |
| Demo day only, 24 hours running, db-f1-micro | **about $0.31, budget $0.50** |
| Same 48-hour weekend on db-g1-small instead | **about $1.79, budget $2** |
| Monthly run-rate if left running, db-f1-micro | **about $9.37/mo, budget $9-10/mo** |
| Monthly run-rate if left running, db-g1-small | **about $27.25/mo, budget $27-28/mo** |
| Stopped but NOT deleted, db-f1-micro, private IP only | about $1.70/mo (storage only) |
| Stopped but NOT deleted, with a public IPv4 kept | up to about $9.00/mo (storage $1.70 + idle IPv4 $7.30) |
| Deleted after the demo | **$0/mo ongoing** |

The single biggest cost control is deleting the instance after the demo. Leaving it running is only about $10/mo on the smallest tier, so a forgotten instance is cheap but not free; a stopped instance with a public IP kept is nearly as expensive as a running one, so delete, do not just stop.

## Assumptions (stated plainly)

- Demo traffic: a handful of users, a few dozen API calls, a few Argon calls, over one weekend (Sun Oct 25, 2026 demo day, teardown right after). Generous sensitivity case below still fits the free tiers.
- Region baseline: us-central1 (Iowa) public list prices, because that is the region the fetched Cloud SQL pricing page displayed. A California region such as us-west2 (Los Angeles, closest to San Francisco) can price slightly differently, and Cloud Run Tier 2 regions cost about 1.4x Tier 1. Re-check the pricing calculator for the region actually chosen before provisioning.
- Month = 730 hours. Storage is billed per GiB-hour, so weekend figures are the monthly figure prorated linearly by hours running. Cloud SQL bills per second while running.
- No high availability (HA), no read replicas, no committed-use discounts (a weekend demo must not buy a 1- or 3-year commitment).
- Cloud Run and Cloud SQL in the same region, connected privately, so same-region Google-to-Google traffic is free.
- No project IDs, keys, or credentials are in this file, and no GCP resources were provisioned for this estimate.
- EXCLUDED from these totals: Gemini/Argon API usage itself. The provisioned hackathon account is AI Studio API only and is separate from GCP billing, so Argon calls do not appear on this GCP bill. If Argon were billed through GCP it would be a separate line; do not mix the two. Also excluded: any pre-existing usage on the same GCP billing account (see the free-tier sharing caveat below).

## 1. Cloud SQL for PostgreSQL

Public list rates used (us-central1, Cloud SQL pricing page):

- db-f1-micro (shared core, 0.6 GiB RAM): $0.0105/hour. Shared-core types are not covered by the Cloud SQL SLA, which is acceptable for a disposable demo.
- db-g1-small (shared core, 1.7 GiB RAM): $0.035/hour.
- SSD storage: $0.000232877/GiB-hour, about $0.17/GiB-month.
- Backup storage (used): $0.000109589/GiB-hour, about $0.08/GiB-month.
- Idle public IPv4 address (while the instance is off): $0.01/hour, about $7.30/month.
- Egress to Google products in the same region: free. Cross-region within North America: $0.12/GiB. Internet egress without Cloud Interconnect: $0.19/GiB.

### Compute

| Tier | Per hour | 24 h | 48 h | 72 h | Per month (730 h) |
|---|---|---|---|---|---|
| db-f1-micro | $0.0105 | $0.25 | $0.50 | $0.76 | $7.67 |
| db-g1-small | $0.035 | $0.84 | $1.68 | $2.52 | $25.55 |
| HA db-f1-micro (do NOT use for a demo) | $0.021 | $0.50 | $1.01 | $1.51 | $15.33 |
| HA db-g1-small (do NOT use for a demo) | $0.07 | $1.68 | $3.36 | $5.04 | $51.10 |

### Storage (10 GB SSD, non-HA)

- Per month: 10 x $0.17 = **$1.70/month**.
- Prorated: 24 h about $0.06, 48 h about $0.11, 72 h about $0.17.
- Storage keeps billing while the instance is stopped. It stops only when the instance is deleted.
- Do not enable automatic storage increase blindly for a demo: provisioned storage never shrinks on its own, so a spike would raise the monthly storage floor.

### IP and backups

- Public IP: $0 while the instance is running (the idle-IPv4 charge applies while the instance is off, not while running). Avoid a public IP entirely: use private IP / the Cloud SQL connector from Cloud Run. If a public IP is kept on a stopped instance, it adds $0.01/hour ($0.24/day, $7.30/month), which is why "stop and forget" is a trap.
- Backups: $0 for this demo because backups are OFF (see cost controls). If backups were on with roughly 10 GB retained, add about $0.80/month, or about $0.05 for a 48-hour weekend. Automated backups plus point-in-time recovery are not needed for a disposable demo database that can be re-seeded.
- Ingress to Cloud SQL is free; egress charges fall on the source side in some paths, so keeping Run and SQL in one region matters more than the per-GiB rate at demo volume.

### Cloud SQL subtotals

| Config | 48-hour weekend | Monthly if left running |
|---|---|---|
| db-f1-micro + 10 GB SSD, backups off, no public IP | $0.50 + $0.11 = **$0.61** | $7.67 + $1.70 = **$9.37** |
| db-g1-small + 10 GB SSD, backups off, no public IP | $1.68 + $0.11 = **$1.79** | $25.55 + $1.70 = **$27.25** |

Cross-check: an independent worked example using the same tier and disk size also lands at $9.37/month for db-f1-micro + 10 GiB, which matches the arithmetic above.

### Which tier to pick

- Start on db-f1-micro. It is the cheapest tier that runs PostgreSQL at all.
- Caveat: 0.6 GiB RAM is tight for PostgreSQL plus concurrent connections. If the demo stutters, connection setup is slow, or the backend holds many idle connections, step up to db-g1-small. The penalty for being wrong is small: only about $1.18 extra for a 48-hour weekend ($1.79 vs $0.61), and about $17.88 extra for a full month.
- Do not pick a dedicated-core Enterprise instance for this demo. The smallest dedicated vCPU alone is $0.0413/hour plus $0.007/GiB-hour of memory, which already exceeds the whole shared-core instance before storage.

## 2. Cloud Run

Public list rates used (request-based billing, Tier 1 regions):

- Requests: $0.40 per million requests beyond the free tier.
- CPU: $0.000024 per vCPU-second (CPU only during requests).
- Memory: $0.0000025 per GiB-second.
- Monthly free tier per billing account: 2 million requests, 180,000 vCPU-seconds, 360,000 GiB-seconds.
- Scales to zero: no charge while no requests are being served, provided no minimum instances are set.

### Demo traffic math

Planned traffic: a few dozen API calls. Even a generous case is nowhere near the free tier:

- Generous case: 1,000 requests, each using 1 vCPU for 2 seconds with 0.5 GiB memory = 2,000 vCPU-seconds and 1,000 GiB-seconds. That is about 1.1% of the free vCPU allowance and 0.3% of the free memory allowance.
- Extreme case: 100,000 requests at the same profile = 200,000 vCPU-seconds, which would exceed the free vCPU allowance by 20,000 seconds, costing about $0.48, plus $0 for requests (still under 2 million). Even a 100x traffic surprise stays under $1 on Cloud Run.

Estimated Cloud Run cost: **$0 for the demo weekend and $0/month at demo traffic**, as long as:

- CPU allocation is request-based (the default), not always-allocated.
- Minimum instances = 0 (scale to zero). A single warm minimum instance is the one setting that turns a $0 service into roughly $10/month, so do not set it for a demo.
- No GPU, no large always-on sidecar.

### Free-tier sharing caveat

The Cloud Run free tier belongs to the billing account, not to one project. If the same GCP billing account already runs other Cloud Run services, the free allowance may already be partly used. At demo volume the overage would still be cents (see the extreme case above), so this does not change the headline.

## 3. Secret Manager

Public list rates used:

- Active secret versions: $0.06 per version per location per month (about $0.000082192 per version per hour).
- Access operations: $0.03 per 10,000 operations.
- Rotation notifications: $0.05 per rotation.
- Management operations (create, update, destroy): free. Destroyed versions: free.
- Monthly free tier per billing account: 6 active versions, 10,000 access operations, 3 rotation notifications.

Demo needs 2 secrets: the API token and the Gemini key.

- With automatic replication (recommended; it bills as one location regardless of how many regions Google replicates to): 2 versions x $0.06 = $0.12/month at list price, but both versions sit inside the 6-free-versions allowance, so **$0**.
- Access operations: the backend should read each secret once at startup and cache it in memory, not on every request. Even reading on every request, a few dozen to a few hundred demo accesses sit inside the 10,000 free operations, so **$0**. Beyond the free tier, 10,000 extra accesses cost $0.03.
- Rotation: not used for a weekend demo, so $0. Do not enable rotation schedules that would send Pub/Sub notifications.
- Warning that does not apply at this scale but matters in general: user-managed replication listing N regions bills N locations per version, so one version in 3 regions would be $0.18/month instead of $0.06. Use automatic replication.

Estimated Secret Manager cost: **$0 for the weekend and $0/month** (list-price value $0.12/month before the free tier).

## 4. Other small costs

| Item | Estimate for demo weekend | Estimate per month if left on | Notes |
|---|---|---|---|
| Egress (Cloud Run to internet, judges' phones) | $0-0.20 | $0-0.20 at demo volume | Demo payloads are JSON and a few images at most; under 1 GiB of internet egress at $0.19/GiB is under $0.20. Same-region Run-to-SQL traffic is free. |
| Cloud Logging / Monitoring | $0 | $0 at demo volume | Demo logs are megabytes, far under typical free ingestion allowances. Keep log volume sane (no per-frame debug logs). |
| Artifact Registry (container image storage) | under $0.10 | under $0.10 | One small Python image, a few hundred MB at most. |
| Cloud Build (if used to build the image) | $0-0.50 | n/a | A couple of builds fit in typical free build minutes; building locally and pushing the image avoids this entirely. |
| DNS / load balancer | $0 | $0 | Not needed. Use the Cloud Run default URL, not a load balancer or custom domain with a paid certificate path. |

Budget a **$0.50 allowance** for this whole "other" bucket in the weekend budget, even though the expected value is close to $0. It does not change the headline: the weekend total stays at about $1 on db-f1-micro.

## 5. Totals

### Demo weekend (recommended config)

| Line | 48 hours | 72 hours |
|---|---|---|
| Cloud SQL compute (db-f1-micro) | $0.50 | $0.76 |
| Cloud SQL storage (10 GB SSD) | $0.11 | $0.17 |
| Cloud SQL backups / public IP | $0.00 | $0.00 |
| Cloud Run | $0.00 | $0.00 |
| Secret Manager (2 secrets) | $0.00 | $0.00 |
| Other (egress, logging, registry) | $0-0.20 | $0-0.20 |
| **Total** | **about $0.61 (budget $1)** | **about $0.93 (budget $1-1.50)** |

Fallback config (db-g1-small, same weekend): $1.79 + $0-0.20 = **about $1.80-2.00 for 48 hours**.

### Monthly run-rate if left running (same config, no teardown)

| Line | db-f1-micro | db-g1-small |
|---|---|---|
| Cloud SQL compute | $7.67 | $25.55 |
| Cloud SQL storage (10 GB SSD) | $1.70 | $1.70 |
| Backups / public IP | $0.00 | $0.00 |
| Cloud Run (demo traffic, scale to zero) | $0.00 | $0.00 |
| Secret Manager (2 secrets, within free tier) | $0.00 | $0.00 |
| Other | $0-0.50 | $0-0.50 |
| **Total** | **about $9.37 (budget $9-10/mo)** | **about $27.25 (budget $27-28/mo)** |

### What "left running" vs "stopped" vs "deleted" actually costs

| End state | Ongoing cost |
|---|---|
| Left running, db-f1-micro | about $9.37/mo |
| Stopped, private IP only | about $1.70/mo (storage only) |
| Stopped, public IPv4 kept | about $9.00/mo (storage $1.70 + idle IP $7.30) |
| Deleted (and secrets / Run service removed or left at $0 scale-to-zero) | $0/mo |

Deleting the SQL instance is the teardown step that matters. Cloud Run at scale-to-zero and Secret Manager inside the free tier cost $0 even if left in place, but deleting the SQL instance is what zeroes the bill.

## 6. Cost controls (checklist for teardown)

1. Smallest tier: db-f1-micro first, db-g1-small only if the demo proves the smaller tier too slow. No HA, no replicas, no dedicated cores.
2. Smallest disk: 10 GB SSD. Turn off automatic storage increase for the demo, or at least watch provisioned size, since increases never shrink on their own.
3. Backups OFF for this disposable instance, including automated backups and point-in-time recovery. Re-seed from the repo instead of restoring.
4. No public IP. Private IP / Cloud SQL connector from Cloud Run only. This also removes the idle-IPv4 trap on a stopped instance.
5. Cloud Run: request-based CPU, minimum instances = 0, maximum instances capped (e.g. 2-5) so a traffic surprise or retry loop cannot scale the bill.
6. Secret Manager: automatic replication, 1 active version per secret, read once at startup and cache. No rotation schedules for the weekend.
7. Same region for Run and SQL. No load balancer, no custom domain, no GPU.
8. Teardown right after the demo, in this order: export anything worth keeping (seed data is already in the repo), delete the Cloud SQL instance, then delete or leave the $0 scale-to-zero Run service and the secrets. Verify in the GCP billing console the next day that the SQL line is gone; a stopped instance still bills storage and possibly an idle IP.
9. Optional offset, NOT counted in the totals above: new GCP customers get $300 in free credits for 90 days, but only if the billing account has not already used them. Do not budget around this; treat any credit as a bonus, not as the plan.

## Sources (public pricing pages checked Oct 25, 2026)

- Cloud SQL pricing (PostgreSQL): shared-core rates, SSD/backup/idle-IPv4/egress rates quoted above.
- Cloud Run pricing summaries: request-based Tier 1 rates and the 2M-request / 180,000-vCPU-second / 360,000-GiB-second monthly free tier.
- Secret Manager pricing summaries: $0.06 per active version per location per month, $0.03 per 10,000 accesses, free tier of 6 versions / 10,000 accesses / 3 rotations.

Caveat repeated: these are estimates from public pages, not quotes. The region actually chosen, the exact tier, and any pre-existing usage on the same billing account can move the numbers by a few dollars per month and by cents for the weekend. The shape of the answer does not change: the whole demo weekend costs about $1, and forgetting to delete the instance costs about $10/month, not hundreds.
