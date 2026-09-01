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

PR #4 merge commit / architectural checkpoint:
`b8eecb349121c917fd141a0c01b5c2aa562af349`.

This SHA is a historical checkpoint, not a forever-current `HEAD`.

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
The staging deployment template sets `RUN_SCHEDULER=false`, so the next staging
deployment from that template is prepared to disable scheduling in the
request-serving API. This describes repository configuration only; it does not
establish that the currently deployed staging revision has this setting.

Production and other runtimes that do not explicitly set the gate retain the
previous in-process scheduler behaviour. Docker still starts Uvicorn with two
workers, Cloud Run may run multiple service instances, and duplicate scheduled
job execution therefore remains a risk wherever the gate is enabled. The
long-term scheduler architecture is **not** solved.

The target direction is a request-serving Cloud Run API plus a separately
scheduled worker or Cloud Run Job, or another design that guarantees one
intended execution of each scheduled workload. This records the required
outcome without prescribing an implementation.

Periodic workloads still need migration to that dedicated execution model.

Address this operational issue separately from the Stage 4 physics migration.

## Staging checkpoint

- Staging exists and is separate from production.
- Staging commands must explicitly target the staging project
  (`heliotelligence-staging`); do not rely on local CLI defaults.
- The staging template is prepared to disable the scheduler on its next
  deployment; assume the current live API scheduler is active unless deployment
  or runtime evidence proves otherwise.

Never put secrets, credentials, or secret values in repository documentation.
