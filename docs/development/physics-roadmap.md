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

As of 2026-10-10, live `main` is:

`359ac6695a19fc9781ca26b96529ed4af0566b87`

This is the merge commit of PR #91, S12D baseline transformer operating-loss evaluation.

S12 milestone merges:

- S12A PR #88 → `7d25a186cc071a524bcbdbeba17f28d9e750fd58`;
- S12B PR #89 → `db78ef563a1c3e68dcacdb13b331a8d06395bbb0`;
- S12C PR #90 → `fc9a22f4145d52acfe092fc8b8d1f11b9e14adfa`;
- S12D PR #91 → `359ac6695a19fc9781ca26b96529ed4af0566b87`.

Reviewed S12 CI history:

| Stage | CI | Run ID | Synthetic merge | Backend | Python | Frontend |
|---|---:|---:|---|---|---|---|
| S12A | #221 | `37703848849` | `38c56f2bb6c8314c59089b42708b9d7ccefd9b6c` | 3121 passed in 319.24s | 3.13.15 | success |
| S12B | #224 | `37850450286` | `bd0645f940cf355d160e30e3484fbccde73ef861` | 3209 passed in 339.52s | 3.13.16 | success |
| S12C | #226 | `37856774002` | `45e06c9918632470b8c7db3812f2259a4477e770` | 3277 passed in 553.18s | 3.13.16 | success |
| S12D | #228 | `38002846864` | `eaa78fdf9bd6bf2c8701d80d8760209ccb3c1b9a` | 3360 passed in 388.38s | 3.13.16 | success |

All reviewed S12 CI used `pvlib==0.15.2`.

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
S9 inverter authority / conversion / accounting / capability / thermal
    ↓
S10 request / feasibility / selected inverter P/Q/S
    ↓
S11A static radial LV topology + direct per-phase R+jX
    ↓
S11B timestamped collection-exit V_LL,RMS
    ↓
S11C balanced radial constant-PQ LV operating solution
    ↓
S12A explicit transformer static equipment + S11 boundary authority
    ├───────────────┐
    ↓               ↓
S12B             S12C
factory loss     timestamped energisation
authority        authority
    \               /
     \             /
      └──────┬────┘
             ↓
S12D current-based factory-reference active-loss baseline
```

S12B and S12C are independent evidence channels. S12D combines canonical S11C and S12A/B/C; it does not solve transformer network-side terminal state.

## Immediate next build

The S12 baseline transformer-loss milestone is complete through S12D. The next priority is the **transformer electrical/network boundary** required before S13 can consume a defensible network-side transformer state.

Design that increment independently rather than reviving the superseded branch-only R/X/G/B S12B proposal unchanged. Explicit electrical authority may eventually include series impedance, terminal magnitude transformation, phase displacement or other parameters where required by the chosen operating solve, but none of those are currently merged.

Do not infer transformer electrical/network authority from rated voltages, labels, geography, S11 exit voltage, capacity, generic efficiency or legacy loss percentages.

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

**Status: baseline transformer-loss milestone complete through S12D; electrical/network terminal propagation still deferred.**

- **S12A — merged/complete:** explicit balanced-three-phase two-winding transformer identity, rated apparent power, rated collection/network `V_LL,RMS`, terminal identities/reference planes, and direct S11 collection-exit binding. No impedance, vector group, taps, losses or operating solve.
- **S12B — merged/complete:** explicit transformer-specific factory-test `P_NL` and total rated `P_LL` with test/reference conditions, provenance and confidence. Missing authority remains missing; no default frequency, temperature or winding material.
- **S12C — merged/complete:** exact timestamped transformer energised/de-energised authority. Explicit `False` resolves; missing is unknown; there is no temporal persistence or inference from power, voltage, daylight or schedule.
- **S12D — merged/complete for baseline loss:** uses delivered S11C collection-boundary P/Q/V to derive current-based loading:
  `I_oper = |S|/(sqrt(3)V)`,
  `I_rated = S_rated/(sqrt(3)V_rated)`,
  `beta_I = I_oper/I_rated`,
  and `P_load = P_LL beta_I²`.
  The model adds `P_NL` only for explicit energised authority, preserves clean de-energised zero loss, detects contradictory de-energised nonzero transfer, and does not clamp overload.

S12D is explicitly a factory-reference baseline. It applies no temperature, harmonic, frequency or voltage-dependent no-load correction; does not decompose aggregate `P_LL`; does not solve transformer R/X/phase displacement; does not allocate loss to a terminal; and does not integrate energy.

The next transformer increment must establish the electrical/network boundary needed to produce a defensible network-side operating state before S13.

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

The physical S8–S12D chain is validated but must not be silently mixed into the legacy production calculation.

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
- S12A–D transformer baseline-loss milestone — merged / complete through reference-condition active-loss baseline;
- transformer electrical/network boundary — next;
- S13 MV/HV collection + explicit revenue-meter boundary — planned;
- S14 benchmarking and causal attribution — planned.
