# P2G AC network + transformer + revenue-meter evidence readiness

**P2G is complete as the current evidence-review package. P2G is not physically
admitted.** The downstream AC path remains blocked until external site evidence
is supplied. This is a reviewed **zero-admission package**: no new authority,
manifest version, evidence-state change, physical-scope change or runtime path is
justified. Future downstream evidence updates P2G in place, not additional P2 letters.

```text
P2G — AC network + transformer + revenue-meter boundary
S11 inverter AC output
          ↓
     LV collection
          ↓
S12 transformer
          ↓
S13 MV/HV network
          ↓
     grid boundary
          ↓
     revenue meter
```

Generic physics capability ≠ Bracon evidence. Migration data ≠ meter authority.
Configured loss percentage ≠ physical impedance/loss authority. Site capacity ≠
transformer rating. Site UUID ≠ revenue-meter identity. Evidence admission also
remains distinct from timestamped resolution and production activation.

Starting checkpoint: PR #138 merge `076c310ce6087048e266bc42cc3bff95b76084d3`.
The [manifest](../../evidence/sites/bracon-ash.yaml) is unchanged at
`bracon-ash-dc-inverter-control-admission-v6`. Its complete serialized state and
66 items are fingerprint-tested against that checkpoint: evidence 17/48/1/0,
admission 6/11/49/0, support 1 full / 5 lower / 60 non-resolving / 0 N/A.
All six P2F admissions retain their exact scope/fidelity. No S11/S12/S13 item is
admitted, bound to authority or sourced from migration CSV data.

## 1. LV collection

**GENERIC CAPABILITY EXISTS.** S11 admits explicit directed radial collection
nodes/segments, inverter-terminal bindings and per-phase series impedance, then
explicit timestamped line-to-line RMS collection-exit voltage. Its operating
solution consumes canonical selected inverter P/Q and preserves network ownership;
it does not infer equipment, voltage, topology or loss percentages.

**SITE EVIDENCE STATUS.** All five requirements remain missing/blocked. Baseline
and full-fidelity blocker sets are unchanged, **5 → 5 / 5 → 5**:

<!-- BEGIN P2G S11 BLOCKERS -->
- `s11.collection_exits`
- `s11.exit_voltage`
- `s11.inverter_terminal_nodes`
- `s11.lv_topology`
- `s11.segment_impedance`
<!-- END P2G S11 BLOCKERS -->

**REQUIRED EXTERNAL EVIDENCE.** Supply LV single-line/as-built drawings, physical
inverter AC terminal IDs and bus/node mapping, segment start/end nodes, electrical
connection topology, conductor/cable paths and schedules, series R/X, nominal/
reference voltage basis, collection exit nodes and collection-exit voltage
authority. Derived impedance must retain conductor material/cross-section/length,
parallel runs, temperature, R/X source, frequency and relevant installation basis.
Nominal voltage context does not replace timestamped operating-voltage evidence.

**PROHIBITED INFERENCE.** Layout groups, inverter labels or geography do not
establish connectivity. `inverter.wiring_loss_ac_pct = 1.70` is not conductor
impedance. No nominal-to-operating voltage, reference plane or branch path is
invented. This review changes no S11 authority, solve or production behavior.

## 2. Transformer

**GENERIC CAPABILITY EXISTS.** S12 separates static equipment/boundary topology,
factory baseline no-load/load-loss evidence, positive-sequence network authority,
operating solution, construction/component losses, thermal and transformer-terminal
harmonic evidence. Advanced/coupled solutions preserve explicit fidelity and can
select an admitted lower-fidelity baseline; they do not add a second transformer
loss beside the baseline. Generic capability does not supply Bracon equipment.

**SITE EVIDENCE STATUS.** All eight S12 requirements remain missing/blocked.
Baseline blockers are unchanged, **5 → 5**:

<!-- BEGIN P2G S12 BASELINE BLOCKERS -->
- `s12.factory_loss_evidence`
- `s12.lower_fidelity_baseline`
- `s12.ratio_tapping_impedance`
- `s12.transformer_equipment`
- `s12.transformer_terminal_binding`
<!-- END P2G S12 BASELINE BLOCKERS -->

Full fidelity additionally requires the following, retaining **7 → 7** blockers:

<!-- BEGIN P2G S12 FULL ADDITIONS -->
- `s12.construction_component_evidence`
- `s12.thermal_evidence`
<!-- END P2G S12 FULL ADDITIONS -->

`s12.harmonic_evidence` remains optional in the catalogue, not a mandatory baseline
blocker. The selected future physical path may independently require it.

**REQUIRED EXTERNAL EVIDENCE.** Supply transformer schedule/nameplates, physical
IDs, S11 collection-exit → transformer-terminal bindings, rated apparent power,
collection/network-side voltages, phase configuration and connection/vector group
where required, turns/voltage ratio, tap position/tapping basis, series impedance
and resistance/reactance basis. Supply factory test reports identifying no-load
and load losses, test conditions, loss reference temperature and provenance.

Advanced fidelity also needs applicable winding conductor/material and resolved
resistance evidence, eddy/other-stray components, construction authority, thermal
state/winding temperatures and transformer-terminal harmonic currents. Raw inverter
spectra alone are not transformer-terminal spectra without explicit aggregation.
A lower-fidelity path still needs reviewed equipment and baseline loss evidence.

**PROHIBITED INFERENCE.** Plant capacity 28,524 kWp, inverter totals, legacy AC
loss or generic assumptions do not establish transformer identity, rating,
connections, loss parameters or a fallback baseline. No transformer is invented.
No unsupported advanced correction is assumed negligible or silently enabled.

## 3. MV/HV network and grid boundary

**GENERIC CAPABILITY EXISTS.** S13A contract
`explicit_mv_hv_network_topology_nominal_pi_and_meter_boundary_authority_v1`
separates network topology, transformer terminal, grid and revenue-meter boundaries.
S13B requires explicit timestamped boundary voltage; S13C solves admitted series/
shunt physics. S12 already owns transformer losses, which S13 does not reapply.
The canonical contract and numerics remain unchanged.

**SITE EVIDENCE STATUS.** All five network/grid requirements remain missing/blocked:

<!-- BEGIN P2G S13 NETWORK BLOCKERS -->
- `s13.grid_boundary`
- `s13.grid_boundary_voltage`
- `s13.mv_hv_topology`
- `s13.segment_parameters`
- `s13.transformer_network_binding`
<!-- END P2G S13 NETWORK BLOCKERS -->

**REQUIRED EXTERNAL EVIDENCE.** Supply MV/HV single-line diagrams, transformer
network-terminal → MV/HV node bindings, nodes/buses, segment connectivity,
cable/line type and schedule, R/X and shunt susceptance/capacitance where required
by nominal-pi authority, voltage basis, grid/POC boundary node and physical export/
import direction. Supply the voltage quantity and exact timestamped grid-boundary
voltage evidence where required; do not substitute nominal voltage context.

**PROHIBITED INFERENCE.** Layout groups, inverter geography, capacity or revenue-
meter rows do not establish MV/HV topology, parameters, grid node or operating
voltage. Meter and grid boundaries are distinct; co-location requires explicit
binding to the same node. No grid or meter boundary is created in this review.

## 4. Revenue meter

**GENERIC CAPABILITY EXISTS.** Existing S13D
[measurement authority](../../src/heliotelligence/physics/revenue_meter_measurement_authority.py)
consumes already-scaled, signed P/Q at an explicit S13A meter boundary. It does not
infer instrument engineering. S14 owns later expected/measured comparisons and
interval reconstruction; P2H retains benchmark/uncertainty and complete P2 closure.
No second measurement solver is introduced here.

**SITE EVIDENCE STATUS.** All four meter requirements remain missing/blocked:

<!-- BEGIN P2G S13 METER BLOCKERS -->
- `s13.revenue_meter_binding`
- `s13.revenue_meter_measurement_semantics`
- `s13.revenue_meter_scaling`
- `s13.revenue_meter_sign_conventions`
<!-- END P2G S13 METER BLOCKERS -->

Together with network/grid requirements these are all nine mandatory S13 baseline
requirements. Baseline/full blocker counts remain **9 → 9 / 9 → 9**.

The reviewed [migration CSV](../../data_migration/ts_meter_readings.csv) contains
6,117 measurement-like rows associated with canonical Bracon site UUID
`5ab83b40-553c-5ddd-976f-71f6cb5d490f`. Its header includes `p_ac_kw`, exported/
imported/net energy fields, phase voltage/current, `freq_hz`, `power_factor`,
`q_kvar` and `quality`. Header presence and site association are migration facts,
not physical evidence. **The migration CSV remains non-authoritative migration
data for P2 evidence purposes.** It is not added to any S13 source references,
and its presence changes no evidence state from missing to present.

It does not establish manufacturer/model/serial, physical meter identity/location,
network node/reference plane, CT/PT ratios, primary/secondary units or scaling
ownership; P/Q signs, import/export or energy-register semantics; averaging,
interval duration, timestamp position/timezone; calibration, accuracy or validity;
or sufficient source-system provenance. Site UUID identifies the site, not a meter.

**REQUIRED EXTERNAL EVIDENCE.** Supply meter identity/nameplate and serial, physical
network location and boundary node/reference plane; CT primary/secondary and VT/PT
ratios where applicable; whether source data is already primary-scaled; P/Q signs,
import/export conventions and energy-register semantics. Specify instantaneous
versus interval-average power, duration, timestamp start/midpoint/end/instant,
timezone and validity dates. Provide calibration/verification, accuracy class or
quantitative specification and source-system/channel provenance. This evidence
must feed the existing canonical measurement boundary. Accuracy-class text alone
does not supply a numerical uncertainty bound; P2H owns that separate admission.

**PROHIBITED INFERENCE.** No numerical patterns are used to infer cumulative
registers, power direction, reactive signs, hourly averaging, CT/PT scaling or
accuracy. No meter ID is synthesized from the site UUID. CSV fields named voltage
or energy do not establish reference planes or boundary bindings. No meter data,
interval semantics or source provenance is promoted to authority by this review.

The four sections above are the four practical procurement bundles in the
[Bracon site request](../sites/bracon-ash.md#p2g-ac-network--transformer--meter-evidence-still-required).
They form one P2G package, not one request per manifest field.

There is currently **no validated allocation** of the legacy 1.70% aggregate AC
loss among LV conductors, transformer and MV/HV network mechanisms. Future physical
S11/S12/S13 activation must explicitly allocate overlapping ownership and prevent
double counting. Do not automatically retain that percentage alongside explicit
physical losses for the same path. P2G neither retires nor redistributes it and
changes no runtime behavior.

P2E upstream and P2F population/DC/inverter/controller gaps remain unchanged.
electrical_topology remains None, and 49,824 / 47,448 / 50,736 remains unresolved.
P2 remains in progress; P3 inactive. P2H is the final consolidated P2 closure
increment. This review adds no site authority YAML, engine authority, physical
source, writer, schema, API or execution path.
