# Physics implementation-delta ledger

## Purpose, source references and control

This is the canonical reconciliation of the original Stage 1–6 engineering intent
with the implemented Heliotelligence authority/reference-plane architecture. Keep
more rigorous canonical physics unchanged. Use design detail to identify
repository documentation alignment, genuine advanced fidelity and site evidence
still required; do not rebuild an effect already represented in the chain.

Reviewed code baseline: PR #131 merge
`879bb186b459b7be344b3ad01337863213b0a086`. Completion status below is contingent
on successful post-merge main CI #335 on that exact SHA. Check live source, tests,
Git history and exact CI before release decisions. This ledger grants no site
admission, runtime resolution or production activation.

The original references are supplied outside the repository. Their exact titles
are identifiers, not repository paths or links to controlled local copies:

1. `Stage_1_-_Irradiance_Modelling.docx`
2. `Stage_2_-_Shading_Model.docx`
3. `Stage_3_-_Cell_Temperature_Model.docx`
4. `Stage_4_-_Module_IV_Curve_and_DC_Power_Model.docx`
5. `Stage_4a_-_String_Aggregation_and_Bypass_Diode_Model.docx`
6. `Stage_5_-_Inverter_Model.docx`
7. `Stage_6_-_Cable_and_Transformer_Loss_Models.docx`

This version records the design intentions supplied for this reconciliation and
checks their implementation ownership against the repository. It does not claim
a page-by-page review, reproduce or modify the external Word files. Those remain
valuable detailed engineering references; enterprise extensions below are not
retroactively attributed to them. The code links substantiate implemented scope.

Each stable ledger row is one reviewed decision unit, possibly grouping related
mechanisms. Every row has exactly one of these four primary dispositions. A
mechanism can have separate rows for its existing code and its site evidence;
that does not assign two primary dispositions to one decision.

| Primary disposition | Decision rule |
| --- | --- |
| `KEEP_CANONICAL` | Current implementation is at least as rigorous as the supplied intent within its admitted coverage. Preserve it; this does not establish site admission or production activation. |
| `DOCUMENTATION_ALIGNMENT` | Intent remains valid, but ownership, stage boundary, reference plane, formula responsibility or model semantics differs. Align repository documentation; code stays canonical. |
| `ADVANCED_FIDELITY_PENDING` | Meaningful design detail is not implemented at that resolution. Future work must extend the existing owners/contracts rather than bypass them. |
| `SITE_EVIDENCE_PENDING` | Generic capability exists or is sufficiently represented, but explicit P2 evidence/binding is required. Missing site evidence is not missing generic code. |

## Canonical ownership and stage mapping

**Stage 1–6 remains a useful conceptual teaching model. S8–S14 and the upstream
authority contracts are the canonical software boundaries.** These naming systems
must not be conflated; this reconciliation creates no new S-stage.

| Original conceptual stage | Canonical software ownership |
| --- | --- |
| Stage 1 Irradiance | Weather-time authority, aligned solar geometry, horizontal components, raw POA and explicit irradiance boundary; overlaps optics only through declared handoffs. |
| Stage 2 Shading | Upstream geometric visibility, optical state, component IAM, rear optics and bifacial treatment; electrical mismatch remains downstream. |
| Stage 3 Cell Temperature | Upstream module thermal authority and timestamped cell/module state; electrical temperature response belongs to the SDM. |
| Stage 4 Module IV | Admitted module electrical state, parameter sourcing, De Soto scaling and SDM, consuming upstream electrical-equivalent irradiance. |
| Stage 4a String / Bypass | S8 homogeneous string baseline, physical common-voltage mismatch and branch reference planes; future member/sub-string/bypass fidelity must enter that boundary. |
| Stage 5 Inverter | S9 conversion/envelope/capability plus S10 request, feasibility and selected P/Q/S; not one efficiency/PF multiplier. |
| Stage 6 Cables / Transformer | S8 direct DC branch, S11 LV collection, S12 transformer and S13 MV/HV/grid/meter, with separate loss ownership. |

```text
UPSTREAM WEATHER / IRRADIANCE / OPTICS / MODULE THERMAL
↓
ADMITTED MODULE ELECTRICAL STATE
↓
S8 STRING / MPPT / PHYSICAL DC MISMATCH / DIRECT DC BRANCH
↓
S9 INVERTER CONVERSION + AC CAPABILITY + THERMAL CAPABILITY
↓
S10 REQUEST / FEASIBILITY / SELECTED P-Q-S
↓
S11 LV AC COLLECTION
↓
S12 TRANSFORMER
↓
S13 MV/HV + GRID / REVENUE-METER BOUNDARY
↓
S14 BENCHMARK / LOSS ATTRIBUTION / UNCERTAINTY INTERPRETATION
```

This is generic capability, not the active production execution graph. Production
still uses the separate legacy `physics_sdm` path described in the
[architecture](physics-architecture.md) and
[production-integration roadmap](../development/production-integration-roadmap.md).

## Mechanism admission and no double counting

A documented mechanism may only be implemented after identifying its canonical
owner, required evidence, reference plane, fidelity level and interaction with
existing mechanisms. It must not duplicate an effect already owned elsewhere in
the chain. Review the relevant contracts and limiting/closure tests before
changing code to resemble an older equation.

The following combinations are prohibited for the same owned effect/path:

- Thermal SDM response plus a separate gamma power correction.
- Bypass-diode mismatch plus a legacy flat shading/mismatch percentage covering it.
- Physical DC branch loss plus legacy DC wiring percentage.
- LV/MV/HV network loss plus legacy AC wiring percentage.
- S12 transformer loss plus transformer loss reapplied in S13.
- Canonical spectral response plus a second spectral factor inside module conversion.

Separate legacy and physical model series may coexist for comparison. That does
not authorise adding their losses, substituting one for missing physics, or
relabeling lower fidelity as advanced. The full evidence rule remains:

```text
generic capability ≠ site evidence ≠ authority admission ≠ timestamp resolution
                   ≠ physical output ≠ production activation
```

## Stage 1 — irradiance

Source reference: `Stage_1_-_Irradiance_Modelling.docx`.

| ID | Design intent / mechanism | Primary disposition | Canonical owner, limit and reconciliation |
| --- | --- | --- | --- |
| I-01 | Weather timestamps, snapshot/interval semantics and solar position | `KEEP_CANONICAL` | [Weather-time authority](../../src/heliotelligence/physics/weather_time_authority.py) and [NREL-SPA alignment](../../src/heliotelligence/physics/solar_geometry_time_alignment.py) separate observation keys from physical evaluation instants. Interval representative-instant geometry is an explicit approximation, not interval integration. |
| I-02 | Horizontal components and GHI-only decomposition | `KEEP_CANONICAL` | [Component resolver](../../src/heliotelligence/physics/irradiance_components.py) preserves supplied complete GHI/DHI/DNI and uses Erbs only for admitted GHI-only rows. Erbs and date-dependent extraterrestrial quantities use the aligned physical time. |
| I-03 | Front transposition and reference planes | `KEEP_CANONICAL` | [Raw front POA](../../src/heliotelligence/physics/poa_transposition.py) supports Perez/Perez-Driesse. [Irradiance boundary](../../src/heliotelligence/physics/irradiance_boundary_state.py) preserves incident, effective and final module-electrical quantities separately. |
| I-04 | Component-resolved IAM and effective irradiance | `KEEP_CANONICAL` | [Optical state](../../src/heliotelligence/physics/optical_state.py) and [effective irradiance](../../src/heliotelligence/physics/effective_irradiance.py) preserve resolved component ownership. Do not copy the legacy scalar/total-POA integration defect into this chain. |
| I-05 | Measured POA as a decomposition/transposition shortcut | `DOCUMENTATION_ALIGNMENT` | Measured front POA is evidence at an explicit plane alongside modelled front, not an automatic replacement. It neither erases rear, means front+rear total, becomes electrical-effective input, establishes thermal POA nor repairs missing optical authority. Preserve both in the irradiance boundary. |
| I-06 | IAM assigned opportunistically inside an irradiance step | `DOCUMENTATION_ALIGNMENT` | IAM belongs to the canonical component optics/effective-irradiance chain. A stage label is not permission to multiply another scalar later. |
| I-07 | Improved decomposition such as Engerer2 | `ADVANCED_FIDELITY_PENDING` | A future validated model option, not currently the canonical GHI-only resolver. Establish material improvement before prioritising it over the bypass/conductor gaps. |
| I-08 | Site source/time and measurement binding | `SITE_EVIDENCE_PENDING` | P2 must admit actual source temporal semantics/duration, receiver coverage and measurement quantity/plane. Source labels, configured paths or a POA field do not establish them. |

Measured front POA ≠ modelled front POA. The thermal handoff in the canonical
irradiance boundary remains deliberately unresolved without an admitted
calibration-basis selection; documentation must not imply an automatic measured
front or front+rear choice.

## Stage 2 — shading and optics

Source reference: `Stage_2_-_Shading_Model.docx`.

| ID | Design intent / mechanism | Primary disposition | Canonical owner, limit and reconciliation |
| --- | --- | --- | --- |
| O-01 | Terrain, inter-row, near-object and explicit 3D/ray shading | `KEEP_CANONICAL` | [Terrain horizon](../../src/heliotelligence/physics/terrain_horizon.py), [fixed rows](../../src/heliotelligence/physics/fixed_inter_row_shading.py), [near objects](../../src/heliotelligence/physics/near_object_shading.py) and [ray backend](../../src/heliotelligence/physics/ray_backend.py) own geometric visibility over their supplied, validated coverage. Clear means clear relative to admitted occluders, not proof of a complete scene. |
| O-02 | Diffuse sky, horizon and ground visibility | `KEEP_CANONICAL` | [Diffuse visibility](../../src/heliotelligence/physics/diffuse_sky_visibility.py) and [diffuse IAM](../../src/heliotelligence/physics/diffuse_iam.py) preserve component-resolved, visibility-conditioned treatment. Ground coverage is the declared flat Lambertian-plane model, not arbitrary terrain/rear obstruction coverage. |
| O-03 | Rear optical and bifacial response | `KEEP_CANONICAL` | [Fixed rear irradiance](../../src/heliotelligence/physics/fixed_bifacial_rear.py), [rear optical state](../../src/heliotelligence/physics/rear_optical_state.py), [row transmission](../../src/heliotelligence/physics/rear_row_optical_transmission.py) and [bifacial equivalent input](../../src/heliotelligence/physics/bifacial_equivalent_irradiance.py) retain their explicit fixed-row coverage. Optical shading does not itself own electrical mismatch. |
| O-04 | PVsyst as principal geometry engine | `DOCUMENTATION_ALIGNMENT` | [Near-shading authority/comparison](../../src/heliotelligence/physics/pvsyst_shading_authority.py) and [horizon authority](../../src/heliotelligence/physics/pvsyst_horizon_authority.py) allow PVsyst evidence, scoped preference and comparison alongside Heliotelligence geometry. They do not make PVsyst the sole runtime geometry engine or extend beam-only authority to unrelated components. |
| O-05 | Constant diffuse masking | `DOCUMENTATION_ALIGNMENT` | Describe the older constant treatment as lower fidelity than component/visibility-conditioned diffuse optics. It must not replace or be multiplied onto the same canonical effect. |
| O-06 | Scene completeness and physical receiver binding | `SITE_EVIDENCE_PENDING` | P2 must admit PVsyst scene scope where used, as-built occluders/geometry and receiver mapping. Bracon's surveyed coordinates/groups provide spatial evidence, not electrical connectivity. |

PVsyst may be source evidence, preferred authority for an admitted scope, or a
comparison benchmark. Preference/fallback must follow the particular authority
contract; it is not a universal selector inferred from a file's presence.

## Stage 3 — module thermal state

Source reference: `Stage_3_-_Cell_Temperature_Model.docx`.

| ID | Design intent / mechanism | Primary disposition | Canonical owner, limit and reconciliation |
| --- | --- | --- | --- |
| T-01 | Direct cell and module-back temperature evidence | `KEEP_CANONICAL` | [Thermal authority](../../src/heliotelligence/physics/module_thermal_authority.py) and [thermal state](../../src/heliotelligence/physics/module_thermal_state.py) distinguish quantities and require explicit back-surface-to-cell conversion, including reference irradiance and deltaT evidence. |
| T-02 | Native steady-state models, zones and environmental inputs | `KEEP_CANONICAL` | Native PVsyst and Faiman authorities, explicit thermal zones, wind requirements, provenance and unresolved states remain canonical. Missing wind is irrelevant only when the admitted coefficient makes its term zero; it is not fabricated. |
| T-03 | Passing shaded/electrical-effective POA directly into thermal balance | `DOCUMENTATION_ALIGNMENT` | Incident broadband irradiance for thermal balance differs from electrical-effective irradiance after optical/electrical response. Thermal POA selection requires explicit calibration-basis authority; IAM/spectral-effective input is not selected automatically. |
| T-04 | Additional `P_corrected = P_STC × [1 + gamma × (T_cell - 25)]` | `DOCUMENTATION_ALIGNMENT` | Stage 3 owns temperature state. Stage 4/SDM owns electrical response to that temperature. Applying this extra gamma power correction after temperature-dependent SDM scaling would double count the thermal response. |
| T-05 | Richer thermal calibration/dynamics | `ADVANCED_FIDELITY_PENDING` | Automated site-calibration workflows, transient thermal inertia, richer zone dynamics and thermal-cycling degradation are potential future capabilities, not current steady-state features. Native coefficient admission and static zone identity already exist. |
| T-06 | Site sensor and model evidence | `SITE_EVIDENCE_PENDING` | Bracon needs quantity, placement/calibration, zone-to-module binding, native parameter basis, required environmental inputs and thermal POA calibration basis. Legacy `u_c/u_v` are not canonical Faiman authority; supplied calibrated native coefficients are evidence, not a new physical equation. |

## Stage 4 — module electrical and I-V

Source reference: `Stage_4_-_Module_IV_Curve_and_DC_Power_Model.docx`.

| ID | Design intent / mechanism | Primary disposition | Canonical owner, limit and reconciliation |
| --- | --- | --- | --- |
| M-01 | Explicit parameters, De Soto scaling and single-diode response | `KEEP_CANONICAL` | [Module lookup](../../src/heliotelligence/physics/module_lookup.py) and [electrical solver](../../src/heliotelligence/physics/electrical.py) retain explicit parameter provenance and tier-dependent support. Voltage-dependent De Soto/SDM curves must not be claimed for a tier that only supports simplified power. |
| M-02 | Receiver/module state and temperature-dependent electrical response | `KEEP_CANONICAL` | The canonical receiver electrical handoff consumes already-resolved electrical-equivalent irradiance and cell temperature. Preserve exact receiver/string routing, module state and unavailable I-V states. |
| M-03 | Spectral correction inside Stage 4; bifacial treatment at the module step | `DOCUMENTATION_ALIGNMENT` | [Spectral response](../../src/heliotelligence/physics/spectral_response.py) and upstream bifacial response own these effects before canonical SDM conversion. `calculate_receiver_module_operating_points_from_spectral_response` consumes that result without a second correction. The separate legacy helper does not define canonical ownership. |
| M-04 | Site module/equipment, spectrum and population | `SITE_EVIDENCE_PENDING` | P2 must bind exact equipment/parameters, spectral activation/evidence and the actual module population. Bracon's configured/module-library labels and conflicting counts do not complete that admission. |

```text
optics → bifacial response → spectral response → module electrical irradiance → SDM
```

The response contracts retain component provenance; this conceptual ordering is
not permission to collapse their separate factors or apply a second rear factor.

## Stage 4a — physical strings, mismatch and bypass diodes

Source reference: `Stage_4a_-_String_Aggregation_and_Bypass_Diode_Model.docx`.

| ID | Design intent / mechanism | Primary disposition | Canonical owner, limit and reconciliation |
| --- | --- | --- | --- |
| A-01 | Physical topology and homogeneous series string I-V | `KEEP_CANONICAL` | [S8 electrical](../../src/heliotelligence/physics/electrical.py) keeps explicit inverter→MPPT→string topology and `homogeneous_series_module_iv_scaling_v1`: V scales by module count, I does not. This is a valid baseline, not member-resolved shading/bypass physics. |
| A-02 | Parallel common-voltage solution and shared-MPPT mismatch | `KEEP_CANONICAL` | S8 solves complete physical strings at shared voltage and preserves independent-string counterfactual versus common-MPPT power. That mismatch owner must not absorb a differently scoped population residual or optical effect. |
| A-03 | Direct string branch and MPPT-input I-V | `KEEP_CANONICAL` | [DC collection](../../src/heliotelligence/physics/dc_collection.py) transforms explicit per-string total loop resistance from `string_terminal` to `mppt_input`, then solves at that sink plane. Preserve V/I/P and branch-loss ownership. |
| A-04 | Bounded intra-string population residual | `KEEP_CANONICAL` | [Population authority](../../src/heliotelligence/physics/module_population_mismatch.py) retains explicit negligible-by-evidence or lower-fidelity post-MPPT equivalent current derate. It is not manufacturing/member I-V physics and consumes no legacy percentage. |
| A-05 | Member/sub-string geometry and topology | `ADVANCED_FIDELITY_PENDING` | Stage4a-1 implements explicit ordered physical module-member and bypass-protected-section topology authority in S8; see the [advanced architecture](advanced-string-bypass-architecture.md). Geometry/shading binding, orientation/routing interpretation and numerical bypass physics remain pending. Existing aggregate geometry supplies no advanced authority. Priority A; partial implementation, not complete Stage 4a. |
| A-06 | Reverse-bias, diode clamping and series sub-string composition | `ADVANCED_FIDELITY_PENDING` | Stage4a-2 implements explicit section reverse-breakdown authority and isolated pvlib Bishop reverse/forward section I-V from already-resolved section SDM state. No module parameter splitting or inferred breakdown scaling. Bypass diode authority/clamp and common-current section/module/string composition remain pending. Do not average member powers or assume missing current-domain/bypass behaviour. Priority A; partial implementation. |
| A-07 | Multi-peak strings and global operating selection | `ADVANCED_FIDELITY_PENDING` | Bypass-induced per-string multi-peak P-V, member/sub-string-resolved nonuniform-string parallel combination, all candidate peaks, global maximum selection and bypass activation diagnostics remain future coverage. Existing S8 already combines differing complete string curves and selects the maximum over its admitted sampled candidate voltages; that is not an all-peaks guarantee for a new bypass-resolved domain. Reuse/extend the existing owner only after validating that domain. Priority A. |
| A-08 | Member-resolved flash-data variability | `ADVANCED_FIDELITY_PENDING` | Explicit flash/I-V population evidence and its member electrical mapping are future higher resolution, not the bounded residual authority. Nameplate tolerance and Bracon's legacy 1.15% do not define a distribution. |
| A-09 | Advanced-path integration and inverter interaction | `DOCUMENTATION_ALIGNMENT` | Future member/sub-string fidelity must produce the existing physical string-terminal boundary, retain the existing branch transform and shared-MPPT owner, and reconcile multi-peak selection with S9's canonical MPPT envelope/selection semantics. Current S9 envelope reports constraints; it does not invent a constrained/global tracking solution. |
| A-10 | Site advanced-path and baseline binding | `SITE_EVIDENCE_PENDING` | P2 needs physical routing, ordering/positions/orientations, string→MPPT assignment, module/sub-string diode layout, shading receiver→module mapping and optional flash data. Bracon currently lacks admitted baseline mapping as well; advanced generic code alone would not admit its advanced route. |

**This is the most important genuine physics delta in the supplied Stage design.**
The existing S8 baseline remains valid where its evidence/fidelity applies and
must not be replaced or relabelled as bypass-resolved.

```text
module electrical state
↓
fidelity selection
├─ baseline: homogeneous string IV
└─ advanced (future): member/sub-string-resolved IV + bypass-diode physics
↓
physical string terminal
↓
existing DC branch transform
↓
existing shared MPPT solve
↓
canonical S9 envelope / conversion ownership
```

Bypass activation diagnostics could improve future fault signatures; an observed
pattern would still require separate validated interpretation and must not be
presented as proof of a fault or causal loss.

## Stage 5 — inverter

Source reference: `Stage_5_-_Inverter_Model.docx`.

| ID | Design intent / mechanism | Primary disposition | Canonical owner, limit and reconciliation |
| --- | --- | --- | --- |
| V-01 | Equipment/model and DC operating envelope | `KEEP_CANONICAL` | [Inverter authority](../../src/heliotelligence/physics/inverter_authority.py), [DC envelope](../../src/heliotelligence/physics/inverter_envelope.py) and [multi-MPPT routing](../../src/heliotelligence/physics/inverter_topology.py) preserve exact model and voltage/current constraints. An aggregate inverter rating is not copied onto each tracker. |
| V-02 | Sandia conversion, independent tracker voltages, clipping/tare | `KEEP_CANONICAL` | [Physical inverter conversion](../../src/heliotelligence/physics/inverter_conversion.py), [pre-limit potential](../../src/heliotelligence/physics/inverter_potential.py) and [accounting](../../src/heliotelligence/physics/inverter_accounting.py) represent one inverter and preserve conversion/clipping/tare distinctions. |
| V-03 | AC nameplate, apparent power, fixed-Q limits and explicit Q requests | `KEEP_CANONICAL` | [AC capability authority](../../src/heliotelligence/physics/inverter_ac_authority.py) and [P/Q/S evaluation](../../src/heliotelligence/physics/inverter_pqs_capability.py) require explicit rated S and admit fixed-Q limits only where supplied. Missing Q request is not zero. |
| V-04 | Thermal capability, temperature, dispatch and selected state | `KEEP_CANONICAL` | [Thermal authority](../../src/heliotelligence/physics/inverter_thermal_authority.py), [temperature capability](../../src/heliotelligence/physics/inverter_temperature_capability.py), [P request](../../src/heliotelligence/physics/inverter_dispatch_request_authority.py), [feasibility](../../src/heliotelligence/physics/inverter_dispatch_feasibility.py) and [selection](../../src/heliotelligence/physics/inverter_dispatch_selection.py) preserve explicit evidence and choose only the fully feasible exact request. |
| V-05 | Reactive operation through `Paco_effective = Paco × PF` | `DOCUMENTATION_ALIGNMENT` | Do not adopt this shortcut. Canonical `S = hypot(P,Q)`, `S <= Smax`, fixed-Q limits and thermal/dispatch constraints are stronger. Operating PF is derived from admitted P/Q where appropriate, not a substitute for Smax authority or a new Paco multiplier. |
| V-06 | Sandia separately per tracker, then sum AC outputs | `DOCUMENTATION_ALIGNMENT` | Canonical multi-input conversion uses `pvlib.inverter.sandia_multi` for one physical inverter, retaining independent tracker voltages and additive DC input. Do not add several independently clipped/tare-charged virtual inverters or average tracker voltages. |
| V-07 | Bracon capability, commands and temperature | `SITE_EVIDENCE_PENDING` | Admit model/equipment binding, static S/P/Q capability, fixed-Q source sign convention/conversion, controller P/Q requests and thermal/temperature evidence. Positive Q is downstream injection; prose alone does not close the S9-4A source-evidence gate. |

## Stage 6 — DC cables and construction-level parameter authority

Source reference: `Stage_6_-_Cable_and_Transformer_Loss_Models.docx`.

| ID | Design intent / mechanism | Primary disposition | Canonical owner, limit and reconciliation |
| --- | --- | --- | --- |
| C-01 | Direct string→MPPT cable loss | `KEEP_CANONICAL` | S8's [explicit branch resistance](../../src/heliotelligence/physics/dc_collection.py) is the baseline for admitted direct paths. Keep the terminal I-V transform; do not restore a flat DC wiring percentage. |
| C-02 | Derive cable parameters from construction evidence | `ADVANCED_FIDELITY_PENDING` | Conductor material, cross-section, length, conductor count, parallel runs, installation arrangement, reference resistance, temperature coefficient and conductor temperature need a reviewed parameter authority. Its outputs feed canonical S8/S11/S13 electrical parameters with explicit unit, phase, loop/reference-temperature bases. Priority B. |
| C-03 | AC cable refinements and installation/thermal environment | `ADVANCED_FIDELITY_PENDING` | Skin/proximity effects, sheath/screen loss, capacitance/charging current and installation/thermal evidence require explicit support. Produce parameters supported by the target solver: S11 currently admits series R/X without shunts; S13 admits nominal-pi series/shunt terms. Unsupported terms require a reviewed extension to that owner, never an independent subtraction engine. Priority B. |
| C-04 | Arbitrary shared post-parallel DC feeders/combiner networks | `ADVANCED_FIDELITY_PENDING` | Direct independent branches do not model arbitrary shared collection. A shared feeder carries total current and cannot be duplicated as a per-string resistor. Extend canonical DC topology/solve ownership where site evidence/use case requires it. |
| C-05 | Cable routing, schedules and operating environment | `SITE_EVIDENCE_PENDING` | P2 must establish actual paths, schedules, construction/installation and temperature evidence as required by the selected fidelity. Geometry distances and legacy wiring percentages do not admit resistance or a detailed IEC-derived authority. |

Advanced cable work derives electrical network parameters; the existing network
solvers continue to own voltage/current/P/Q and resulting losses. Sheath or
charging effects cannot simply be subtracted again from their solved output.

## Stage 6 — LV, MV and HV networks

Source reference: `Stage_6_-_Cable_and_Transformer_Loss_Models.docx`.

| ID | Design intent / mechanism | Primary disposition | Canonical owner, limit and reconciliation |
| --- | --- | --- | --- |
| N-01 | Physical AC collection and conservation | `KEEP_CANONICAL` | [S11 authority](../../src/heliotelligence/physics/lv_ac_collection_authority.py)/[solve](../../src/heliotelligence/physics/lv_ac_collection_operating.py) and [S13 authority](../../src/heliotelligence/physics/mv_hv_network_authority.py)/[solve](../../src/heliotelligence/physics/mv_hv_operating_solution.py) retain explicit radial balanced nodes/segments, R/X, MV/HV nominal-pi B/shunts, timestamped boundary voltage, P/Q conservation and distinct planes. They do not claim arbitrary unbalanced-network coverage. |
| N-02 | One conceptual AC cable/transformer loss stage | `DOCUMENTATION_ALIGNMENT` | Separate inverter AC output → S11 LV network → transformer collection terminal → S12 → transformer network terminal → S13 MV/HV → grid boundary → meter boundary. Do not collapse these planes or reapply transformer/legacy AC losses. |
| N-03 | Site network and operating-voltage package | `SITE_EVIDENCE_PENDING` | P2 must bind actual LV/MV/HV topology, terminal identities, per-phase/segment parameters and timestamped exit/grid voltages. Nominal voltage, groups and coordinates are not operating boundary authority. |

## Stage 6 — transformer

Source reference: `Stage_6_-_Cable_and_Transformer_Loss_Models.docx`.

| ID | Design intent / mechanism | Primary disposition | Canonical owner, limit and reconciliation |
| --- | --- | --- | --- |
| X-01 | Equipment, boundary topology, no-load/rated load loss and series equivalent | `KEEP_CANONICAL` | [Static authority](../../src/heliotelligence/physics/transformer_authority.py), [factory losses](../../src/heliotelligence/physics/transformer_loss_authority.py), [positive-sequence equivalent](../../src/heliotelligence/physics/transformer_series_equivalent.py) and [terminal solve](../../src/heliotelligence/physics/transformer_operating_solution.py) already exceed a universal aggregate-loss expression. |
| X-02 | Advanced winding/current/harmonic/temperature/core physics | `KEEP_CANONICAL` | [Component/material authority](../../src/heliotelligence/physics/transformer_loss_component_authority.py), [terminal current spectra](../../src/heliotelligence/physics/transformer_harmonic_current_authority.py), [thermal evidence](../../src/heliotelligence/physics/transformer_thermal_state_authority.py), [corrected load loss](../../src/heliotelligence/physics/transformer_corrected_load_loss.py) and [core/no-load model](../../src/heliotelligence/physics/transformer_core_no_load_loss.py) own I2R, winding eddy/other stray, current-based factors, temperature and winding-resolved corrections where admitted. Core treatment is bounded voltage/frequency-dependent active loss; do not imply saturation, excitation Q or transient thermal iteration. |
| X-03 | Lower fidelity and coupled terminals | `KEEP_CANONICAL` | [S12M coupled solution](../../src/heliotelligence/physics/transformer_advanced_operating_solution.py) replaces baseline load/no-load sinks with selected physics, preserves explicit S12G load-loss fallback and reconciles terminals. Selected correction is never additive to the same factory/baseline loss. |
| X-04 | Real-power-based transformer load fraction | `DOCUMENTATION_ALIGNMENT` | Do not regress advanced load loss to `beta = P_actual / S_rated`. Current loading controls the admitted current-dependent correction, including reactive loading. A simple two-parameter description is explanatory lower fidelity only where independently admitted; it is not universal truth or permission to change S12's equations. |
| X-05 | Site transformer evidence and selected fidelity | `SITE_EVIDENCE_PENDING` | P2 must establish equipment/terminal bindings, factory baseline losses and advanced construction/winding/material, terminal harmonic and temperature evidence where required. Inverter type-test spectra are not transformer-terminal spectra without documented aggregation. Valid baseline evidence can support an explicit lower-fidelity path without inventing advanced inputs. |

## Meter boundary, benchmarking and uncertainty — enterprise extensions

These capabilities extend beyond the original seven references. Their provenance
is current repository development, not a claim that the Stage documents specified
them retrospectively.

| ID | Design intent / mechanism | Primary disposition | Canonical owner, limit and reconciliation |
| --- | --- | --- | --- |
| B-01 | Explicit expected/measured meter boundary | `KEEP_CANONICAL` | [S13 network/meter binding](../../src/heliotelligence/physics/mv_hv_network_authority.py) and [measured P/Q authority](../../src/heliotelligence/physics/revenue_meter_measurement_authority.py) keep physical plane, scaling, signs and time semantics. Grid and meter boundaries are co-located only by explicit binding. |
| B-02 | Instantaneous/interval benchmarks and delivery accounting | `KEEP_CANONICAL` | [Power benchmark](../../src/heliotelligence/physics/revenue_meter_power_benchmark.py), [interval benchmark](../../src/heliotelligence/physics/revenue_meter_interval_benchmark.py), [support policy](../../src/heliotelligence/physics/revenue_meter_interval_support_policy.py) and [delivery attribution](../../src/heliotelligence/physics/revenue_meter_loss_attribution.py) retain exact support/interval semantics and eligibility. Accounting is not causal diagnosis. |
| B-03 | Complete generic deterministic uncertainty stack | `KEEP_CANONICAL` | [Measurement](../../src/heliotelligence/physics/revenue_meter_measurement_uncertainty.py), [pointwise model](../../src/heliotelligence/physics/revenue_meter_expected_model_uncertainty.py), [discrete interval propagation](../../src/heliotelligence/physics/revenue_meter_expected_model_interval_uncertainty.py), [combined bounds](../../src/heliotelligence/physics/revenue_meter_combined_interval_uncertainty.py) and [eligible envelope interpretation](../../src/heliotelligence/physics/revenue_meter_interval_uncertainty_interpretation.py) preserve separate evidence and ownership. Discrete propagation excludes support-density/continuous-path error. Ineligible rows are not interpreted; no probability, statistical significance, causal loss or commercial impact is established. |
| B-04 | Meter, support-policy and numerical uncertainty admission | `SITE_EVIDENCE_PENDING` | P2 must admit physical meter/scaling/sign/time evidence, maximum-gap policy and numerical complete-chain measurement/model bounds. Labels, cadence, confidence and nominal accuracy classes supply no inferred numerical bound or universal gap threshold. |

## P0–P6 integration governance

| ID | Design intent / mechanism | Primary disposition | Canonical owner, limit and reconciliation |
| --- | --- | --- | --- |
| G-01 | Source isolation through controlled retirement | `KEEP_CANONICAL` | [Production roadmap](../development/production-integration-roadmap.md): P0 source isolation; P1 physical shadow-output contract; P2 site evidence/admission; P3 shadow execution; P4 reconciliation/validation; P5 controlled cutover; P6 mechanism-specific legacy retirement. These are integration phases, not physics mechanisms or new S-stages. |
| G-02 | Site readiness after P2A | `SITE_EVIDENCE_PENDING` | [P2A manifest](site-evidence-manifest.md) and [Bracon record](../sites/bracon-ash.md) identify 66 requirements: 17 present/not admitted, 48 missing/blocked, one conflicting/blocked, zero admitted. The 49,824 / 47,448 / 50,736 population conflict remains unresolved; all nine path sections remain blocked. P2 is incomplete and P3 inactive. |

P2B current-status note: G-02 records the original zero-admission P2A baseline.
The current manifest now admits only the reviewed physical-site identity (1
admitted / 16 not admitted / 49 blocked); all nine paths are only partially
admitted and retain blockers. Identity supplies no evidence for Priority A or B;
both remain `ADVANCED_FIDELITY_PENDING`. Full P2 remains incomplete and P3 inactive.

Status after successful main CI #335:

```text
P0 source isolation — COMPLETE
platform authorization — COMPLETE
P1 physical output contract — COMPLETE
P2A evidence manifest/baseline — COMPLETE
P2 site authority admission — IN PROGRESS
P3 shadow execution — INACTIVE
```

This ledger does not modify P1, the manifest/catalogue, site configuration or any
execution/selection behavior. It is not itself Twin evidence or an admission.

## Priority and relationship to P2

**Priority A: advanced S8 member/sub-string and bypass-diode physics (A-05–A-07).**
This is the highest-value unresolved detailed mechanism from the supplied design:
electrical shading/mismatch, multi-peak behavior and more resolved future fault
signatures. Its generic implementation and site use require explicit physical
mapping and diode/current-domain evidence. Preserve the current baseline path. Stage4a-1 now supplies dormant member/section connectivity authority only; A-05 geometry/shading binding and A-06 clamp/composition and A-07 multi-peak work remain pending; Stage4a-2 now supplies isolated explicit section Bishop I-V.

**Priority B: advanced cable/conductor parameter authority (C-02–C-03).** The
network solvers already own rigorous electrical solutions; the principal missing
piece is deriving appropriate electrical parameters from construction evidence.
Feed those parameters into existing S8/S11/S13 owners, rather than creating a
second cable-loss engine. Preserve S12 transformer ownership in that chain.

Lower-priority refinements include Engerer2, thermal coefficient-calibration
workflows/dynamics, member flash-data variability, arbitrary shared DC collection
and additional cable thermal physics where site scale/evidence justifies them.
A site requiring a shared feeder cannot call independent branch coverage a valid
representation of that feeder merely because the extension is lower priority.

Do not automatically implement every advanced model before P2. P2 must establish:

1. What evidence the site actually has.
2. Which physical path/fidelity is defensible.
3. Which advanced capability would materially improve that admitted site model.

If Bracon lacks module/sub-string routing, a future generic bypass engine cannot
be site-admitted there. If cable schedules/conductor data are absent, a detailed
IEC-derived parameter authority cannot be populated honestly. Missing in the
current repository package does not prove that external evidence cannot exist.

Advanced items do not automatically block every P3 shadow run. An independently
valid lower-fidelity physical path may be admitted only with explicit intended
fidelity, evidence, reference planes and coverage limits, plus the other P3 gates.
This is neither a blanket exemption nor permission to activate Bracon or choose a
source now. P2 remains incomplete.

## Digital Twin connection and change control

```text
Detailed design documents
        ↓
Implementation-delta ledger
        ↓
Canonical physics capabilities + P2 admitted site evidence
        ↓
Twin Definition + timestamped physical state
        ↓
Twin State
        ↓
P3 shadow execution / UI projection
```

Geometry is one evidence layer, not the whole Twin Definition. A design equation
or ledger row cannot supply an absent asset mapping or establish a timestamped
state. Future increments must cite their row, canonical owner, evidence package,
reference plane, selected fidelity, non-overlap rule and validation plan. Revise
the row's disposition only after the corresponding reviewed capability or site
admission exists; do not close a code gap solely by changing prose.
