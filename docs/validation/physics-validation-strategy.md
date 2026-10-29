# Physics Validation Strategy

Physics validation progresses from exact local identities to site evidence. Higher levels do not replace lower-level tests.

## Validation philosophy

Every new physical layer should answer four questions independently:

1. Is the local equation / algorithm correct?
2. Is the input authority valid and tamper resistant?
3. Does the handoff to the next reference plane close exactly?
4. Is the model supported by the site's available topology/equipment data?

A model that matches site output but violates one of these rules is not accepted.

## Level 1 — algebra / identities

Examples:

- series voltage scaling;
- current conservation;
- `P = V × I` where that identity is the represented state;
- resistive drop `ΔV = I × R`;
- resistive loss `P_loss = I²R`;
- conversion / clipping accounting closure;
- `S² = P² + Q²` once S9-4B exists.

## Level 2 — limiting and boundary cases

Examples:

- identical strings sharing an MPPT produce approximately zero physical mismatch when their I-V curves are identical;
- explicit zero resistance produces an identity branch transform;
- zero irradiance yields the appropriate inactive / zero electrical state;
- exact MPPT/inverter voltage and current limits follow documented inclusivity;
- `Praw == Paco` is at the AC nameplate boundary but has zero clipping loss;
- `Pdc == Pso` follows normal Sandia conversion, while `Pdc < Pso` follows the below-startup tare regime;
- missing authority remains unresolved instead of becoming zero;
- missing fixed-Q authority is distinct from explicit `Qmin = Qmax = 0`;
- contradictory `three_phase + single_phase_terminal` capability authority is rejected.

## Level 3 — reference-model comparison

Compare suitable layers against public pvlib calculations, pinned-version private helpers only as test oracles where no public pre-limit reference exists, datasheet/manufacturer operating points, known analytical cases, and independent engineering calculations.

Production code must not depend on a private reference helper merely because it is useful as a test oracle.

## Level 4 — exact admission and handoff closure

When a stage consumes a structured result from an upstream stage, prefer exact canonical replay when practical.

Validation should cover:

- exact result type;
- exact diagnostics type;
- exact DataFrame / index / ordering;
- stable dtypes, including empty-result schemas;
- state vocabulary;
- provenance and model IDs;
- reference-plane labels;
- diagnostics closure against independent source authority;
- rejection of coherent downstream tampering.

The S8/S9 chain deliberately uses this pattern so a caller cannot alter a seemingly plausible upstream result and still obtain an authoritative downstream state.

## Level 5 — system equivalence and migration safety

Before replacing a legacy layer in production, demonstrate expected equivalence under conditions where legacy and physical models should agree. Differences outside those conditions must be explainable from physical assumptions.

Production migration must explicitly prove:

- no physical loss is applied twice;
- legacy aggregate percentages are removed or bypassed at the correct boundary;
- unresolved physical authority falls back safely and transparently;
- reference planes are aligned;
- production outputs remain deterministic.

A validated dormant physics module is not automatically approved for production activation.

## Level 6 — site validation

Compare against, where authoritative and aligned:

- SCADA;
- inverter telemetry;
- weather / irradiance sensors;
- the revenue meter;
- commissioning / factory test data;
- PVsyst or another engineering model where appropriate.

Do not tune away structural physics errors with unexplained empirical correction factors. Site-data fit is evidence, not permission to conceal an incorrect mechanism.

## Current validated trace

Current canonical code checkpoint: `1a4b06f1b3ba6fa8dc26d859cb55b5de25accc4a` (PR #121 merge on `main`). Live GitHub CI must be rechecked for release/merge decisions. Git history and GitHub Actions are the authoritative historical record.

```text
UPSTREAM WEATHER / IRRADIANCE / MODULE THERMAL
(production-readiness validation still required)
↓
ADMITTED MODULE ELECTRICAL STATE
↓
S8 STRING / MPPT / PHYSICAL DC MISMATCH / DIRECT DC BRANCH
↓
S9 INVERTER CONVERSION + AC CAPABILITY + THERMAL CAPABILITY
↓
S10 EXPLICIT REQUEST / FEASIBILITY / SELECTED AC P-Q-S
↓
S11 LV AC COLLECTION
↓
S12 TRANSFORMER
↓
S13 MV/HV COLLECTION + GRID/REVENUE-METER BOUNDARY
↓
S14 METER BENCHMARK + DELIVERY-LOSS ATTRIBUTION
```

Evidence determines fidelity; fidelity determines available physics. Missing advanced evidence must not destroy a valid lower-fidelity physical solution where an independently valid lower-fidelity model exists. Fallback must never be relabelled as advanced fidelity. It must be explicit, physically valid, provenance-bearing and contractually distinguishable; arbitrary numerical fallback is not permitted.

Generic validation does not establish site readiness or production activation. The current generic validation claim is strongest for the S8–S14 electrical chain; it must not be used to imply that the legacy weather/POA/module-thermal runtime is a canonical validated end-to-end upstream chain.

## Required invariants for S8/S9

### String / MPPT

- series voltage scales with module count;
- series current does not scale with module count;
- common-voltage aggregation never sums independent MPP powers as the actual connected operating point;
- mixed active / zero strings remain unresolved where blocking behaviour is unknown.

### Direct DC branch

- explicit zero resistance is a resolved ideal path;
- missing resistance authority is unresolved;
- total loop resistance is not auto-doubled;
- no geometry / ID / aggregate-loss inference is accepted;
- transformed curve follows `V' = V - I R`.

### Shared DC network

Current direct-branch support must not be misrepresented as shared feeder support. A future shared edge must operate on total junction current and be validated separately.

### Inverter envelope

- independent MPPT voltages are never averaged;
- inverter-level current limits are not copied to every tracker;
- unresolved current authority remains visible;
- classification does not silently clamp / re-solve the DC state.

### Sandia conversion

- one physical inverter is converted once;
- multi-MPPT voltage rails remain independent;
- power aggregation follows pinned Sandia semantics;
- `Paco` and night tare are applied once per inverter.

### Pre-limit potential and accounting

For applicable rows:

```text
conversion_delta = Pdc - Praw
conversion_loss - conversion_gain = conversion_delta
clipping_loss = Praw - Pac
net_delta = Pdc - Pac
Pdc + gain - loss - clipping = Pac
```

Additional guards:

- `Praw > Paco` ↔ clipping active;
- `Praw == Paco` → zero clipping loss;
- `Praw > Pdc` is preserved as empirical conversion gain;
- negative `Praw` above startup is not reclassified as tare;
- tare-only rows keep conversion/clipping quantities not-applicable.

### S9-4A static AC capability authority

The authority layer must remain independent of timestamped operating state.

Required invariants:

- every resolved row exactly replays the supplied authority object;
- missing mapping entries remain unresolved with NaN numerics and explicit unresolved state;
- stable empty/populated DataFrame dtypes;
- exact contract/model/scope/coverage provenance on every row;
- diagnostics close independently against topology and explicit authority mapping;
- no inference from `Paco`, CEC/SAM `Vac`, `pnom_kwac`, grid limits, `model_ref`, groups, MPPT/string counts, topology position or legacy AC wiring loss;
- `three_phase + single_phase_terminal` is invalid;
- fixed Q limits must be both present or both absent;
- fixed-Q evidence uses `Q > 0` = AC-network injection and `Q < 0` = absorption; source evidence using another convention must be transformed before S9-4A authority construction;
- each fixed-Q magnitude must not exceed `Smax`;
- missing fixed-Q authority is different from explicit zero Q capability;
- no P/Q/S operating state, AC current, PF compliance, thermal derating, controller, cable or transformer physics appears in S9-4A.

### S9-4B P/Q/S capability-state evaluation

S9-4B is now validated.

Required invariants include:

- exact replay/admission of canonical S9-3B and S9-4A inputs;
- request keys are `(timestamp, inverter_id)`;
- explicit request source/confidence and Q sign convention are preserved;
- missing request is distinct from explicit Q=0;
- `S = hypot(P,Q)`;
- exact inclusive Smax and fixed-Q boundary semantics under the declared tolerance;
- partial authority remains unknown rather than a false pass when fixed-Q authority is absent;
- known circle/fixed-Q violations remain definitive;
- `|P| > Smax` remains a known violation even when Q is missing;
- inactive Sandia states are resolved not-applicable;
- unresolved S9-3B state propagates, including NaN active power;
- static full-capability authority is inherited from S9-4A independently of request presence;
- mapping insertion order cannot change canonical output order;
- P and Q are never changed to force feasibility;
- no AC-current, thermal, controller, cable or transformer physics appears in S9-4B.

### S9-4C thermal-derating authority

S9-4C is now validated.

Required invariants include:

- exact topology-order replay of explicit per-inverter authority;
- missing authority distinct from explicit no-derating authority;
- explicit non-empty temperature quantity;
- finite strictly increasing temperature domain;
- immutable aligned P/S/Q curve tuples;
- exact partial-channel authority without fabrication;
- per-point P<=S and |Q|<=S where those channels coexist;
- Qmin<=Qmax with asymmetric capability allowed;
- positive Q = injection and negative Q = absorption;
- no automatic sign reversal;
- linear interpolation recorded only as downstream metadata;
- outside-domain policy recorded as unresolved;
- no interpolation or timestamped operating evaluation;
- no module/cell-temperature reuse;
- no S9-4A/S9-4B coupling;
- exact provenance, diagnostics, dtypes, ordering and ownership;
- no dispatch, AC current, network or production integration.

### S9-4D temperature-dependent inverter capability

S9-4D is now validated.

Required invariants include:

- exact replay/admission of canonical S9-4B and S9-4C;
- exact timestamped `InverterTemperatureState` keyed by `(timestamp, inverter_id)`;
- explicit temperature quantity, source and confidence;
- exact case-sensitive basis match to S9-4C;
- inclusive temperature-domain boundaries;
- unresolved state outside the authority domain;
- no clamping or extrapolation;
- exact authority-value replay at breakpoints;
- piecewise-linear interpolation only between explicit points;
- explicit no-derating authority distinct from missing authority;
- only explicitly supplied P/S/Q thermal channels evaluated;
- absent thermal channels preserved as partial authority;
- known upstream or thermal violations remain definitive;
- static S9-4A/S9-4B capability and S9-4C thermal authority remain separately attributable;
- no controller dispatch, P/Q/S modification, AC current, thermal-loss accounting, cables or transformers;
- exact dtypes, provenance, state semantics, diagnostics and deterministic full-result closure.

### S10A explicit inverter active-power dispatch-request authority

Required invariants include:

- exact replay/admission of canonical S9-4D;
- canonical `(timestamp, inverter_id)` universe/order;
- finite non-negative P setpoints;
- explicit zero distinct from missing request;
- exact `inverter_ac_output` reference plane;
- no temporal persistence or resampling;
- no inference from available power, nameplate, `grid_limit_kwac`, measured output or plant export limit;
- no duplicate reactive-power authority.

### S10B requested dispatch feasibility

Required invariants include:

- strong exact replay of S9-4D and S10A;
- requested P only from S10A;
- requested Q only from canonical S9-4B request;
- `S_requested = hypot(P_requested,Q_requested)`;
- independent checks for instantaneous P availability, static S/Q limits and thermal P/S/Q limits;
- known violations remain definitive under partial information;
- passing partial authority remains partial/unknown;
- no P/Q clipping, substitution, selection or plant-level allocation.

### S10C selected inverter AC dispatch state

Required invariants include:

- strong exact replay of canonical S10B;
- selection only for `resolved_requested_dispatch_feasible_full_capability` with resolved/applicable/no-violation/satisfied closure;
- exact selected P/Q/S passthrough from the request;
- finite selected values with P >= 0 and S >= 0;
- exact Q injection/absorption/zero semantics;
- no selected point for known infeasible, partial-authority or unresolved feasibility;
- inactive state resolved/not-applicable without fabricated zero;
- no P clamp, Q clip, S-circle projection, thermal clip or fallback policy;
- selected-count and Q-direction diagnostic partitions close exactly;
- selected target is not measured output;
- no AC current/network physics or curtailment accounting.

## Validated S11 progression

S11 followed the authority-first sequence and is complete through S11C.

### S11A static LV collection authority

Validation covers exact balanced-three-phase/line-to-line/per-phase-series basis, node and segment identity, direct non-negative R/X including explicit zero, inverter-terminal binding, acyclic radial/outdegree rules, ordered terminal-to-exit paths, shared segments, multiple trees, malformed-versus-partial authority, immutable ownership, and independent path/diagnostic closure. No topology or impedance is inferred.

### S11B collection-exit voltage authority

Validation covers strong S11A replay, exact `(pd.Timestamp, collection_exit_node_id)` keys, collection-exit-only reference plane, finite non-negative line-to-line RMS voltage, explicit zero versus missing, explicit-timestamp × canonical-exit closure, no temporal/cross-exit inference, immutable ownership, provenance, and independent diagnostics.

### S11C balanced radial operating solve

Validation covers:

- strong S10C, S11A, and S11B replay, including rejection of mutable-but-equal S11A/S11B result mappings;
- pure numerical-kernel tests separated from expensive parent admission;
- analytical single-resistive-feeder current/voltage regression;
- positive Q and reactive absorption;
- shared-feeder complex-current aggregation and shared `3R|I|²` loss exactly once;
- multilevel and independent trees;
- exact zero dispatch and zero-exit-voltage cases;
- missing authority/dispatch/boundary handling;
- deterministic nonconvergence and nonfinite handling with unresolved physical values;
- independent validator tree-membership and diagnostics reconstruction;
- output tamper rejection;
- terminal constant-PQ, junction KCL, segment `V=ZI`, segment complex-power/loss, exit delivery, and whole-tree P/Q conservation closure.

S11C solved state remains modeled, not measured, and does not validate voltage compliance, transformer behavior, controller feedback, or energy integration.

## Validated S12 transformer invariants

- Explicit positive-sequence transfer, tapping/ratio and impedance reference-side ownership; no extra referral.
- Factory series equivalent closes to admitted total load loss; terminal P/Q/V/current and baseline loss conserve.
- Component I²R/eddy/OSL decomposition closes to factory evidence; harmonic h²/ h^0.8 weighting is distinct from temperature dependence.
- Scalar and winding-resolved thermal correction preserve explicit side evidence and homogeneous custom-authority precedence; no inferred/averaged temperatures.
- Effective aggregate I²R/eddy factors reproduce winding sums; S12M reconstructs fundamental/harmonic coefficients at S12K's construction current.
- Aggregate OSL remains unsplit; missing defensible proxy produces unresolved advanced correction with a valid selected S12G fallback where available.
- Core/no-load scaling and its explicit valid factory fallback retain ownership; contradictory evidence is not a fallback licence.
- S12M fixed point reconciles core voltage and coupled-current loss on one converged iterate, supports both reference sides and preserves P/Q conservation.
- Harmonic active sink remains separate from voltage-drop resistance; no thermal iteration is claimed.
- Parent canonical replay rejects representative new winding fields; independent validation succeeds with production helpers disabled.

## Validated S13 network/boundary invariants

- Topology authority and exact grid-boundary voltage precede the balanced radial nominal-pi solve.
- Canonical S12M P/Q is admitted for advanced and valid S12G-load-loss fallback; deenergised retains zero-transfer semantics.
- The same transformer terminal-voltage tolerances apply to both energised resolved states. Mismatch stays unresolved.
- Series/shunt consumption, meter-boundary expected P/Q and active/reactive conservation close without reapplying transformer loss.
- Mixed advanced/fallback trees resolve when evidence is complete, while exact fidelity and fallback fields remain visible.
- Missing/nonfinite/nonconvergent states remain unresolved. Independent validator reconstructs readiness and rejects fidelity/provenance tampering.

## Validated S14 benchmark/accounting invariants

- Exact expected/measured meter identity, physical boundary and timestamp alignment; snapshot and interval-average measurements remain distinct.
- Exact interval endpoint/support eligibility, piecewise-linear expected power and trapezoidal integration; no nearest-time substitution or extrapolation.
- Delivery accounting closes selected source, LV loss, transformer loss, network consumption and expected meter output.
- Valid transformer fallback supports resolved instantaneous/interval accounting using generic total-loss fields, not advanced-only fields.
- Deterministic fallback ID tuples and presence flags reconstruct from canonical contributing S12M states; interval provenance unions all admitted support timestamps.
- Residual remains measured minus expected, never a hidden correction or automatic causal allocation.
- Canonical replay/tamper rejection and independent validator monkeypatch proofs remain required.

## Pre-shadow validation gates

P0 source isolation is necessary but does not by itself make a physical shadow series trustworthy. Before P3/P4, add focused validation for the following:

### Weather temporal semantics — generic contract implemented

- distinguish instantaneous weather values from interval averages;
- retain source interval and label semantics;
- define the representative solar-position instant used for interval irradiance;
- prove start/mid/end interval equivalence, explicit midpoint approximation, DST physical elapsed duration, unsorted-index preservation and invalid-combination rejection; compare morning midpoint SPA directly against both midpoint and endpoint references at the existing solar-model tolerance.

Generic contracts are now implemented but do not establish source/site temporal evidence or integrate nonlinear geometry across an interval.

### Irradiance and optics ownership — generic boundary implemented

- a non-unity IAM must measurably change the electrical irradiance/power path exactly once;
- measured-front POA on a bifacial site must not silently erase a separately admitted rear contribution;
- front transposition, shading, IAM, spectral and rear contributions must have one owner each;
- real canonical optical chains feed the new boundary in focused regressions; no shadow orchestration is activated;
- measured front 800 W/m² coexists with canonical rear 120 W/m² without replacement/zeroing or automatic 920 W/m² handoff;
- explicit spectral disabled resolves its admitted no-op while unknown unresolved spectral state stays unresolved;
- exact timestamp/receiver/timezone/order mismatches, public-field tampering and diagnostic changes are rejected by independent replay.

Thermal incident candidates remain separate from spectral electrical irradiance. Calibrated module-thermal POA selection is intentionally deferred, not silently inferred from a diagnostic sum. Site evidence and actual production integration remain open.

### Module thermal state

The generic canonical module thermal contract is now implemented and tested separately from unchanged legacy `physics/thermal.py`. Focused validation covers:

- explicit temperature quantity and reference plane/basis;
- measured module/backsheet temperature versus calculated cell temperature semantics;
- explicit module-back conversion authority: deltaT=3°C at E_ref=1000 W/m² produces 53°C from 50°C at 1000 W/m² and 52.1°C at 700 W/m²; the separate legacy regression remains 50.021°C at 700 W/m²;
- declared thermal-model family and parameter semantics;
- native PVsyst/Faiman parameter separation with no automatic conversion; any externally converted native parameters require explicit provenance;
- per-timestamp direct-cell → measured-module conversion → native-model precedence, with both measurement channels preserved and unusable-measurement model fallback explicit;
- missing POA/ambient/required wind and missing conversion reasons; zero wind coefficients resolve without inventing wind observations;
- exact timezone-aware unique/non-NaT grids and measurement keys, deterministic order, invalid numeric/provenance rejection and typed empty results;
- independent equation/provenance/schema/diagnostics reconstruction and tamper rejection, including validation with production builders and pvlib disabled;
- no interpolation, extrapolation, persistence, thermal inertia, site inference or production activation.

Thermal POA is supplied incident broadband irradiance, not automatically electrical-effective irradiance. Weather representative-instant semantics, thermal-zone mapping, Bracon Ash sensor/model admission and production handoff remain separate gates. The generic contract alone does not validate a site timestamp.

### Mismatch coverage

Validate the new dormant population-residual boundary separately from physical shared-MPPT mismatch and homogeneous series scaling. Admit only explicit negligible (f=0) or equivalent post-MPPT current derate (0<f<1), with exact scope excluding shared MPPT and all other losses. Nameplate tolerance alone and the legacy aggregate percentage are not resolving authority.

Required regressions prove unchanged V, I_after=I_common(1−f), P_after=VI, population=P_common−P_after, and total=shared+population=P_independent−P_after. Preserve upstream shared mismatch. Test active, zero, unresolved, missing and partial authority. Zero must resolve exactly without authority, be fraction-independent with authority, retain no fabricated fraction/provenance, and never count as a missing-authority gap. Mixed night/day coverage must distinguish zero resolution from active missing authority. Test repeated MPPT IDs scoped by inverter, empty grids, extra/empty-MPPT keys and invalid authority domains/provenance.

Independently verify the published aggregated S8 contract and its internal consistency: exact types, topology row universe, timezone/duplicates, contracts/models, state/count consistency, P=VI, mismatch/percentage closure and every diagnostics count. Verify topology-ordered unresolved IDs, sorted unique non-empty cause tokens from the admitted S8-1 vocabulary, and reject unknown causes without inventing member-to-cause assignments. Independently validate output replay and tamper rejection with production builders disabled. Prove no legacy percentage leakage and unchanged S8 numerical behaviour through the immediate string/MPPT regression slice.

Generic bounded coverage is implemented; site admission remains evidence-dependent. Bracon is not admitted and 1.15% is not retired. Member-resolved reverse/bypass physics remains outside this lower-fidelity contract. Do not retire the full legacy percentage until ownership closes.

### S14B support density

Generic S14B v2 support eligibility is implemented, dormant. Prove reconstruction resolved ≠ benchmark eligible: exact boundaries/all resolved samples and finite integration can coexist with missing policy or excessive support gap. Such rows retain expected averages/energy, measured energy and support diagnostics; all eight benchmark residual fields remain NaN. Only explicit policy with actual maximum gap ≤ admitted seconds allows eligibility. No default or gap-fraction threshold is inferred.

Test frozen authority domains/provenance and tamper revalidation, meter-specific/partial mappings, unknown keys, explicit reuse and insertion-order invariance. Test inclusive equality, irregular-gap integration invariance, missing-policy diagnostics, earlier failure precedence and constant-power rejection under a stricter policy. Policy counts partition only finite reconstructed intervals, excluding snapshot/upstream-failure rows.

Synthetic sunrise proxy `P(x)=P_peak*x²` and mirrored sunset `P(x)=P_peak*(1−x)²`, 0≤x≤1, have exact average P_peak/3. Endpoint-only trapezoids give P_peak/2; four equal support segments give 11*P_peak/32. With test-only P_peak=96, exact/sparse/denser averages are 32/48/33 and absolute errors 16/1. A test-only 900-second policy admits the quarter-hour support and rejects one-hour endpoints. These are analytic regression facts only, not Bracon or universal PV accuracy/cadence claims.

Independently replay support timestamps, gaps/fraction, policy lookup, provenance, eligibility, residual publication and diagnostics with production record/integration/frame/policy helpers disabled. Tampering with every new field and count must fail. S14C regressions must resolve under passing policy and suppress component-energy attribution under missing/excess-gap policy, using S14B's exact published support rather than a new downstream interpretation. S14A and S14C accounting physics remain unchanged.

### Quantitative uncertainty

Categorical `confidence` is provenance metadata, not numerical uncertainty. P4 validation should retain, where available:

- meter accuracy class / numerical accuracy specification;
- CT/PT or scaling-chain accuracy;
- calibration evidence and applicability;
- material model/input uncertainty or bounded sensitivity.

Acceptance thresholds must account for admitted measurement/model uncertainty rather than interpreting every residual as model error.

### Platform authorization

Before shadow results are exposed outside the trusted development team, test that:

- admin authorization does not depend on a browser-bundled shared `VITE_ADMIN_KEY`;
- authenticated users cannot access another site's data without server-side membership/role authority;
- each protected site-scoped route performs the same authorization decision;
- negative cross-site access tests exist for expected energy, benchmarking, reports and other site data.

## Next validation target — production-integration migration safety

Follow the [production-integration roadmap](../development/production-integration-roadmap.md). P0 source isolation is complete at `04f0cf338ab86980c040e5b6fbda6942a3c28681`; retain its no-mixing/overwrite regressions. The generic canonical module thermal gate is implemented, and generic weather-time/irradiance-boundary capability is now implemented. The next workstream is quantitative uncertainty, platform authorization and site evidence binding including population-residual and S14B support-policy authority before P1/P2 finalisation. Then validate shadow-output reference plane, timestamp identity, fidelity/provenance, uncertainty and unresolved coverage. Compare aligned meter output and ownership across representative operating regimes before any per-site cutover.

No legacy percentage may remain active for a mechanism/path already owned by the physical model in that same expected series. Unknown legacy allocation requires an evidence decision. Site fallback must be explicit physics, never silent reversion to percentages inside a physical source.

## Regression matrix for each change

During development, run focused changed-stage tests. Before PR review, run focused feature tests and the immediate parent/downstream regression slice, Ruff, formatting checks, strict mypy where relevant, Python compilation and `git diff --check`. Run optical/rear regressions when shared dependencies warrant them.

GitHub CI is the authoritative full-backend validation. Do not repeatedly run the full local backend after hardening changes. A full local suite may be run deliberately when justified, but is not the default. Documentation-only changes require Markdown/link/whitespace checks rather than backend tests. Check the exact base/head and live CI for review or release decisions.

## Site and portfolio validation

Validation should progress through:

`component → site → portfolio`

Portfolio validation is a future layer above site validation. A good aggregate portfolio result must not be used as evidence that individual site models are correct. Each site's inputs, intermediate states, constraints, confidence, and losses must remain independently testable and explainable.
