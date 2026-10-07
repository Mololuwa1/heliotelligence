# Physics Development Roadmap

This roadmap describes dependency order, not a fixed pull-request numbering scheme. Stage and PR numbers may change as evidence, data authority, and review boundaries evolve.

Source-of-truth order for implementation status is:

1. live source code;
2. automated tests;
3. Git history and exact commit ancestry;
4. exact GitHub Actions CI;
5. architecture documentation;
6. implementation reports and conversation notes.

The project is beyond MVP. New physics should remain narrow, provenance-aware, explicit about unresolved state, and dormant from production until independently validated.





## Current canonical checkpoint

As of 2026-10-06, live `main` is:

`6f6dbb34027f9e648fe8623aab37b14341f193c7`

This is the merge commit of PR #86, S11C balanced radial LV AC collection solve.

Controller milestone merges:

- S10A PR #79 → `4a6b318946a5a2bb688bfa29f7318403362f99de`;
- S10B PR #81 → `2f4a4050c48203018fbf914c3853675f996bda97`;
- S10C PR #82 → `a8e883b4ba04dfcab4a2736d15ceaf9eed06496e`.

S11 milestone merges:

- S11A PR #84 → `caabb06ff31d5b5cf48139fada6aeb265ae9771a`;
- S11B PR #85 → `3fb4c3181c283ecf62622865b88622ac7b24ae22`;
- S11C PR #86 → `6f6dbb34027f9e648fe8623aab37b14341f193c7`.

Final reviewed S11C CI used head `73dafc1f79c09ccd9fb61dd9ee7610cc2e62233c`:

- run #217;
- run ID `37544412809`;
- synthetic merge `a8ea3ec4965e75f2ae67dae835a74dc619bf4d2e`;
- Python 3.13.15;
- `pvlib==0.15.2`;
- backend `3040 passed in 527.89s`;
- frontend success.

## Current validated electrical chain

```text
module electrical state
    ↓
S8-1 physical string I-V
    ↓
S8-2 source-plane common-voltage MPPT / physical mismatch
    ↓
S8-3A explicit direct-branch resistance authority
    ↓
S8-3B resistive branch I-V transform
    ↓
S8-3C MPPT-input common-voltage operating point
    ↓
S9-0 explicit inverter CEC/SAM authority
    ↓
S9-1 inverter DC operating-envelope classification
    ↓
S9-2 one-physical-inverter Sandia AC conversion
    ↓
S9-3A Sandia pre-Paco AC potential
    ↓
S9-3B conversion / clipping / tare accounting
    ↓
S9-4A static inverter AC capability authority
    ↓
S9-4B timestamped P/Q/S capability-state evaluation
    + S9-4C explicit thermal authority
    + explicit timestamped inverter temperature
    ↓
S9-4D temperature-dependent capability evaluation
    ↓
S10A explicit active-power dispatch request
    ↓
S10B requested P/Q/S feasibility
    ↓
S10C selected inverter AC P/Q/S
    ↓
S11A static radial topology + direct per-phase R+jX
    ↓
S11B timestamped collection-exit V_LL,RMS
    ↓
S11C balanced radial constant-PQ LV operating solution
```

- **S10A — merged:** direct timestamped per-inverter absolute P request at `inverter_ac_output`; missing ≠ zero; no persistence; no duplicate Q authority.
- **S10B — merged:** exact requested-point feasibility against instantaneous availability, static S/Q capability and thermal P/S/Q capability; no P/Q/S modification.
- **S10C — merged:** exact feasible-request passthrough only; infeasible, partial and unresolved requests do not produce a selected point; no clamping, projection or fallback policy.

## Immediate next build

S11 v1 is complete. The next priority is **S12 — transformer**, beginning with explicit transformer equipment/topology and reference-plane authority. Do not infer a transformer, winding boundary, voltage ratio, rating, impedance, loss, or tap state from S11 exit voltage, CEC `Vac`, labels, capacities, geometry, or current site YAML.

## Next system stages after inverter capability

### S10 — plant-controller / dispatch boundary

**Status: complete through S10C.**

S10 deliberately separates:

```text
available physical capability
→ explicit request
→ exact requested-point feasibility
→ selected exact feasible request
```

The current v1 controller chain does not infer how a real controller resolves infeasible commands. It does not clamp P, clip Q, project P/Q to a capability boundary, allocate a plant export limit, persist commands through time or claim selected state is measured output.

Causal curtailment/lost-energy accounting remains downstream work and must not be inferred merely from the existence of a selected target.

### S11 — physical LV AC collection

**Status: complete through S11C; dormant from production.**

- **S11A — merged/complete:** explicit balanced-three-phase radial nodes, direct per-phase segment R+jX, inverter-terminal bindings, collection exits, shared paths, and multiple trees.
- **S11B — merged/complete:** explicit timestamped line-to-line RMS voltage magnitude at exact collection exits; zero differs from missing; no temporal inference.
- **S11C — merged/complete:** balanced constant-PQ backward/forward sweep with modeled node voltage, segment current/P/Q, instantaneous series loss/consumption, and whole-tree conservation.

S11C assumes the S10C selected target is realised; it is not measured output. Physical loss is `3R|I|²`, not energy and not a percentage. `wiring_loss_ac_pct` remains a separate legacy compatibility input and must not be double counted. No S11D physics increment is currently required; future energy integration, reporting aggregation, telemetry reconciliation, or production activation are separate concerns.

### S12 — transformer model

The authority-first transformer sequence should begin with explicit equipment/topology evidence, potentially covering only when authorised:

- terminal/reference-plane definition and winding voltage bases;
- rated power and turns/voltage ratio;
- series impedance and copper-loss authority;
- no-load/core-loss authority;
- loading and tap/control evidence only when explicit.

Operating transformer physics follows only after the required authority exists. `lv_ac_collection_exit` is not automatically a transformer winding.

### S13 — MV/HV collection + explicit revenue-meter boundary

Extend the same network-element pattern through MV feeders, collection transformers where applicable, main transformer, HV/export assets, and the explicit revenue-meter boundary.

Expected and actual values must refer to the same meter boundary before benchmarking residuals are computed.

### S14 — benchmarking and causal loss attribution

Once the end-to-end expected physical chain reaches the meter boundary, build production-grade benchmarking around validated intermediate states.

Target outputs include expected vs actual at aligned boundaries, telescoping loss waterfalls, conversion/clipping/curtailment/cable/transformer/network buckets, availability/underperformance residuals, model confidence, provenance, and anomaly diagnostics without double counting.


## S9-4A / S9-4B merged capability semantics

S9-4A establishes static inverter-level equipment facts only.

Resolved S9-4A fields include:

- nominal AC voltage;
- voltage basis: `line_to_line`, `line_to_neutral`, or `single_phase_terminal`;
- phase configuration: `single_phase` or `three_phase`;
- rated apparent power `Smax`;
- optional fixed `Qmin/Qmax` pair;
- parameter source and confidence.

S9-4B then evaluates timestamped operating requests without control action:

```text
P = admitted S9-3B p_ac_available_w
Q = explicit timestamped request
S = hypot(P, Q)
```

S9-4B semantics:

- positive Q = injection; negative Q = absorption;
- missing Q != explicit Q=0;
- `S <= Smax` is always evaluated where P/Q are admitted;
- fixed Q limits are evaluated only when S9-4A supplies them;
- missing fixed-Q authority yields partial capability rather than a false pass;
- `|P| > Smax` is a definitive violation even with missing Q;
- full static capability authority is inherited from S9-4A independently of request availability;
- night-tare/non-producing rows are resolved not-applicable;
- no dispatch, P curtailment, Q clamping, AC current, thermal derating, wiring or transformer modelling occurs.

Safety rules across both stages:

- no `Smax = Paco` inference;
- no AC voltage inference from CEC/SAM `Vac`;
- no inference from `pnom_kwac`, grid/export limits, topology labels, model refs, groups, MPPT/string counts, or legacy AC wiring loss;
- `three_phase + single_phase_terminal` is invalid;
- missing fixed-Q authority and explicit zero fixed-Q capability remain distinct.

## Deferred shared DC collection extension

The current S8-3 path supports explicit **direct per-string branch resistance** to the parent MPPT input. It does **not** claim arbitrary DC collection-network coverage.

Shared post-parallel conductors remain a separate required extension.

```text
String A -- Ra --\
                  +-- collection node -- Rh -- MPPT
String B -- Rb --/
```

A shared resistance `Rh` acts on total junction current and must not be copied into each branch.

Return to generalized DC collection:

1. before claiming arbitrary DC network support; or
2. before benchmarking / activating a site whose as-built topology includes material shared post-parallel conductors.

## Optical and surface work still required

Enterprise completeness still requires targeted extensions including dynamic physical/measured soiling, snow, arbitrary 3D rear obstruction/terrain/tracker coverage, and substring/bypass-diode partial-shading electrical behaviour.

The intended partial-shading chain remains:

`module irradiance distribution → substring/bypass behaviour → module I-V → string I-V → multiple local maxima → MPPT tracking behaviour`

Do not substitute scalar mismatch or shading percentages for this mechanism.

## Production integration remains separate

The physical S8/S9 chain is validated but must not be silently mixed into the legacy production calculation.

The compatibility path still includes aggregate effects such as soiling, LID, static mismatch, DC wiring, and legacy AC wiring / grid-cap behaviour.

Physical replacements should enter production only through a separately reviewed migration proving reference-plane alignment, no double counting, safe unresolved behaviour, equivalence where mechanisms overlap, and clear fallback semantics for sites without required authority.

## Validation milestones

For new physics increments, use a non-redundant validation cadence:

1. focused tests for the new stage;
2. immediate-parent regression;
3. Ruff, strict mypy, syntax compilation and `git diff --check`;
4. one full backend run before PR review;
5. one fresh synthetic-merge CI run after the PR is opened or corrected.

Do not repeatedly run nested overlapping suites when the full backend already subsumes them unless a specific regression investigation requires it.

Architectural milestones:

- S8 physical DC/string/MPPT chain — merged;
- S9 inverter conversion/capability/thermal chain — merged;
- S10 request/feasibility/selection controller chain — merged;
- S11A static LV collection authority — merged / complete;
- S11B collection-exit voltage authority — merged / complete;
- S11C balanced radial LV operating solve — merged / complete;
- S11 v1 — complete;
- S12 transformer authority — next;
- S13 MV/HV collection + explicit revenue-meter boundary — planned;
- S14 benchmarking and causal attribution — planned.
