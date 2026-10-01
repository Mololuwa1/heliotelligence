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

As of 2026-10-01, live `main` is:

`28f4ada0b3ac9a29762cbbbb094de967d2ca0902`

This is the merge commit of PR #70, S9-4A explicit inverter AC capability authority.

Final pre-merge CI for PR #70:

- run #184;
- run ID `36933743300`;
- synthetic merge `5f4cd71af55fa287e0f0ddd0022c1c9955c504f5`;
- Python 3.13.15;
- `pvlib==0.15.2`;
- backend `2614 passed in 165.95s`;
- frontend success.

No separate post-merge run was associated with the merge commit at the time of this update. Always re-check live GitHub before treating this SHA as current.

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
S9-3B conversion / clipping / tare power accounting

parallel static branch:
S9-4A explicit inverter AC capability authority
```

Status by stage:

- **S8-1 — merged:** homogeneous physical string I-V scaling.
- **S8-2 — merged:** source-plane common-voltage MPPT and IV-consistent mismatch.
- **S8-3A — merged:** explicit direct string-branch resistance authority.
- **S8-3B — merged:** string-terminal to MPPT-input resistive I-V transform.
- **S8-3C — merged:** MPPT-input common-voltage operating point.
- **S9-0 — merged:** exact inverter ID → CEC/SAM Sandia authority.
- **S9-1 — merged:** DC voltage/current envelope classification with explicit tracker-current authority where required.
- **S9-2 — merged:** single- or multi-MPPT Sandia conversion for one physical inverter, without voltage averaging or duplicated inverter limits.
- **S9-3A — merged:** model-native Sandia pre-Paco AC potential.
- **S9-3B — merged:** conversion / empirical gain / Paco clipping / below-startup tare accounting with exact closure.
- **S9-4A — merged:** static explicit inverter AC capability authority for voltage, voltage basis, phase, `Smax`, optional fixed Q limits, provenance and confidence.

## Immediate next build

The next priority is **S9-4B — inverter P/Q/S capability-state evaluation**.

Do not jump directly to AC cabling. Physical AC collection loss depends on current, and AC current depends on voltage, phase configuration, active power, reactive power, and apparent power.

### S9-4B — inverter P/Q/S capability-state evaluation

S9-4B should combine:

```text
S9-3B admitted p_ac_available_w
+
S9-4A static AC capability authority
+
explicit requested Q
```

and evaluate the requested operating state without dispatching it.

Core quantities:

```text
P = admitted active power
Q = explicit requested reactive power
S = sqrt(P^2 + Q^2)
```

Required capability checks:

- apparent-power circle: `S <= Smax`;
- fixed-Q range only where S9-4A supplies explicit `Qmin/Qmax`;
- explicit unresolved state where required authority or operating input is absent;
- explicit distinction between complete capability authority and a partial check based only on `Smax`.

Rules:

- define and test the Q sign convention explicitly in this stage;
- do not silently change P or Q to make a request feasible;
- do not call a request feasible solely from the `Smax` circle when manufacturer Q/PF capability is otherwise unknown;
- do not infer Q limits from `Smax`, `Paco`, CEC/SAM `Vac`, active-power rating, or grid limits;
- do not calculate AC network losses in this stage.

### S9-4C — inverter thermal derating, only with explicit authority

Add thermal derating only where defensible manufacturer curves or validated operating-temperature authority exist.

Potential inputs include ambient or inverter temperature, manufacturer derating curves/breakpoints, temperature-dependent active/apparent capability, source and confidence.

Do not invent derating curves from nameplate power or ambient temperature.

## Next system stages after inverter capability

### S10 — plant-controller / dispatch boundary

Separate **available AC** from **dispatched AC**.

This layer should own:

- active-power curtailment;
- export setpoints;
- reactive-power / PF commands;
- grid-controller limits;
- command provenance;
- controller-induced curtailment accounting.

Do not fold controller effects into Sandia conversion loss.

### S11 — physical LV AC collection

Build topology-aware LV collection only after AC voltage and P/Q/S state are explicit.

Target physics:

- segment graph / from-node / to-node connectivity;
- conductor resistance using authoritative length / conductor data;
- current derived from admitted AC electrical state;
- `I²R` loss;
- voltage drop;
- downstream P/Q state;
- explicit unresolved handling when topology or conductor authority is missing.

Do not retain a static AC wiring percentage where physical network inputs are available.

### S12 — transformer model

Preferred first transformer increment:

- explicit transformer equipment authority;
- no-load / core loss;
- load loss from factory-test or manufacturer data;
- loading based on admitted P/Q/S;
- independent energised / de-energised state;
- exact input/output power accounting.

### S13 — MV/HV collection and revenue-meter boundary

Extend the same network-element pattern through MV feeders, collection transformers where applicable, main transformer, HV/export assets, and the explicit revenue-meter boundary.

Expected and actual values must refer to the same meter boundary before benchmarking residuals are computed.

### S14 — benchmarking and causal loss attribution

Once the end-to-end expected physical chain reaches the meter boundary, build production-grade benchmarking around validated intermediate states.

Target outputs include expected vs actual at aligned boundaries, telescoping loss waterfalls, conversion/clipping/curtailment/cable/transformer/network buckets, availability/underperformance residuals, model confidence, provenance, and anomaly diagnostics without double counting.

## S9-4A merged authority semantics

S9-4A establishes static inverter-level equipment facts only.

Resolved fields:

- nominal AC voltage;
- voltage basis: `line_to_line`, `line_to_neutral`, or `single_phase_terminal`;
- phase configuration: `single_phase` or `three_phase`;
- rated apparent power `Smax`;
- optional fixed `Qmin/Qmax` pair;
- parameter source and confidence.

Safety rules:

- no `Smax = Paco` inference;
- no AC voltage inference from CEC/SAM `Vac`;
- no inference from `pnom_kwac`, grid/export limits, topology labels, model refs, groups, MPPT/string counts, or legacy AC wiring loss;
- `three_phase + single_phase_terminal` is invalid;
- missing fixed-Q authority and explicit zero fixed-Q capability remain distinct;
- S9-4A performs no P/Q/S operating calculation, AC current calculation, dispatch, thermal derating, AC wiring or transformer modelling.

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

Every physical increment should include, as applicable:

- exact upstream replay / tamper resistance;
- focused unit physics tests;
- limiting-case tests;
- conservation and accounting closure;
- comparison with pvlib or another reference calculation;
- synthetic topology tests;
- provenance and deterministic ordering tests;
- full backend and frontend CI;
- only later, site SCADA / revenue-meter / PVsyst validation.
