# Heliotelligence AI / Developer Handoff

This is a recovery and architectural checkpoint document. It does not replace
the repository, automated tests, Git history, or direct inspection of current
code.

## Recovery rule

When beginning from a new conversation or development session:

1. Query Git for the current `main`, then fetch it.
2. Read this file.
3. Read `docs/architecture/physics-architecture.md`.
4. Read `docs/development/physics-roadmap.md`.
5. Inspect open pull requests.
6. Read the relevant implementation and tests.
7. Treat current source, tests, and Git history as authoritative when
   documentation or remembered conversation context disagrees.

Do not trust a SHA written in documentation as "current main" indefinitely.
Always query Git first.

## Last architectural checkpoint

- PR #1 — Environment / CI foundation — merged.
- PR #2 — Electrical topology foundation — merged.
- PR #3 — Stage 4 module operating-point refactor — merged.
- PR #4 — Topology-aware string and MPPT aggregation — merged.
- PR #5 — Project handoff / architecture documentation foundation — merged.
- PR #6 — Scheduler execution gate — merged.
- PR #7 — Application logging visibility — merged.

PR #4 merge commit / architectural checkpoint:
`b8eecb349121c917fd141a0c01b5c2aa562af349`.

Current operational checkpoint merge commit:
`e3186f288fb8a0da723809648c306e2527acb926`.

These SHAs are historical checkpoints, not forever-current `HEAD` values.
Always query Git for the current `main`.

## Current Stage 4 capability

Stage 4 currently provides:

- tiered module parameter resolution;
- De Soto and single-diode electrical modelling;
- a PVWatts fallback;
- spectral correction when inputs are available;
- module Pmp, Vmp, and Imp;
- ideal module-to-string series scaling;
- explicit `Site → Inverter → MPPT → String` topology contracts;
- per-string operating states; and
- an independent-string MPPT counterfactual:

  `P_independent = Σ Pmp,string`

This is **not** yet actual common-MPPT power.

## Current temporary behaviour

`calculate_dc_power()` retains the compatibility loss cascade:

`soiling → LID → static mismatch → DC wiring`

- `mismatch_loss_pct` remains active.
- `wiring_loss_dc_pct` remains active.
- `soiling_loss_pct` and `lid_loss_pct` remain active.
- This is deliberate while physical replacements are validated.
- These percentages do not represent the final target physical models.

## Next physics step

The next electrical work is voltage-dependent module/string I-V capability.
That capability is required before implementing:

`I_MPPT(V) = Σ I_string(V)`

`P_actual = max_V [V × I_MPPT(V)]`

`P_mismatch = P_independent - P_actual`

These equations describe planned work; they are not currently implemented.

## Non-negotiable project rules

- Use physics-first modelling where a mechanism can reasonably be calculated.
- Do not replace one arbitrary loss percentage with another disguised
  approximation.
- Preserve legacy behaviour until its replacement is independently validated.
- Prefer focused PRs with equivalence and physics tests.
- Do not invent unavailable physical topology.
- Bracon Ash MPPT/string mapping is unknown and must not be invented.
- Never generalize Bracon Ash-specific values—such as modules per string,
  module or inverter model, inverter count, grid limit, or legacy loss
  percentages—to another site unless that site's configuration establishes
  them.
- Sites without sufficient topology must retain a safe compatibility path.
- Do not integrate new physical layers into production before validating their
  lower-level contracts.

## Reference site: Bracon Ash

Bracon Ash is the current reference site used during development. It is one
onboarded site, not a template whose equipment, topology, grid, or loss values
should be assumed for future sites.

See [`docs/sites/bracon-ash.md`](sites/bracon-ash.md) for established site facts,
known data gaps, and an unresolved capacity arithmetic discrepancy. In
particular, no physical MPPT-to-string map is currently known.

## Known operational issue: in-process scheduler

`RUN_SCHEDULER` now explicitly controls whether a FastAPI process configures
and starts APScheduler. Its default is `true` for backwards compatibility.
The request-serving staging API is now validated with in-process scheduling
disabled through `RUN_SCHEDULER=false`.

Production and other runtimes that do not explicitly set the gate retain the
previous in-process scheduler behaviour. Docker still starts Uvicorn with two
workers, Cloud Run may run multiple service instances, and duplicate scheduled
job execution therefore remains a risk wherever the gate is enabled. The
staging work did not change production.

The long-term scheduler architecture is **not** solved. Periodic workloads
still require a dedicated execution model. A likely direction is Cloud
Scheduler plus a Cloud Run Job or worker, or another mechanism that guarantees
one intended execution of each workload, but the exact architecture has not
been selected and no dedicated executor currently exists.

Address this operational issue separately from the Stage 4 physics migration.

## Application logging checkpoint

PR #7 added application-specific logging for the `heliotelligence` namespace.
`settings.log_level` is now consumed, application INFO lifecycle records are
observable, and Uvicorn/root logging is not globally replaced. This enabled
runtime verification of the scheduler gate.

## Staging checkpoint

- Project: `heliotelligence-staging`.
- Validated Git SHA: `e3186f288fb8a0da723809648c306e2527acb926`.
- Validated Cloud Build: `c5a8788c-62cb-499c-b2e5-7902ee4fe0d6`.
- Validated image: `api:e3186f2` at digest
  `sha256:1c101683cc35310a89b60e2d521ea138fc00fc62e2216625f9931dea5dc42a2d`.
- Validated Cloud Run revision: `heliotelligence-api-staging-00004-4bn`,
  receiving 100% of traffic.
- Runtime configuration: `RUN_SCHEDULER=false` and `APP_ENV=staging`.
- Health validation: HTTP 200, application status `ok`, and database status
  `ok`.

Runtime logs showed:

- `Starting Heliotelligence API (environment=staging)`;
- `Synced 2 site(s) to database`;
- `In-process APScheduler disabled by RUN_SCHEDULER`;
- no `APScheduler started`; and
- no `APScheduler stopped`.

Each lifecycle message appeared twice because the container runs two Uvicorn
workers. These duplicate startup messages are not duplicate scheduler
execution. The request-serving staging API is validated with in-process
scheduling disabled.

Staging exists separately from production. Always target the staging project
explicitly for staging commands; do not rely on local CLI defaults.

Never put secrets, credentials, or secret values in repository documentation.
