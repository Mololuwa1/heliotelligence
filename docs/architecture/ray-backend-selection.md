# S5A production mesh ray-backend selection

Date: 2026-09-14  
Base: `aabf52468a51252cc2dcbd1c8e239ab1cd92daf2`

## Decision

**SELECT TRIMESH + EMBREEX.**

Heliotelligence will use Trimesh as a thin scene/triangle-index integration layer and
embreex as its CPU acceleration engine in S5B. Open3D was faster on this host, but
Open3D 0.19.0 has no CPython 3.13 wheel and its Linux wheel and installed dependency
tree are much larger. Correctness and deployability outrank benchmark speed.

This record selects a backend only. It does not add either candidate to runtime
dependencies, change canonical geometry, or route production shading through a mesh
engine.

## Candidates and current package evidence

| Candidate | Version tested | Python / wheel evidence | License |
|---|---:|---|---|
| Trimesh | 5.1.0 | Python >=3.10; universal Python wheel; classifiers include 3.11-3.13 | MIT |
| embreex | 4.4.0 | binary wheels observed for CPython 3.11, 3.12 and 3.13, including Linux x86_64 manylinux 2.27/2.28 | BSD 2-Clause |
| Open3D | 0.19.0 | CPython 3.11/3.12 Linux wheels observed; no CPython 3.13 distribution | MIT |

Primary evidence: [Trimesh PyPI](https://pypi.org/project/trimesh/),
[Trimesh ray API](https://trimesh.org/trimesh.ray.ray_pyembree.html),
[embreex PyPI](https://pypi.org/project/embreex/),
[Open3D PyPI](https://pypi.org/project/open3d/), and
[Open3D RaycastingScene API](https://www.open3d.org/docs/release/python_api/open3d.t.geometry.RaycastingScene.html).
Package facts are current observations, not permanent pins.

On the benchmark host, isolated installed site-packages occupied 105 MiB for the
Trimesh environment (including NumPy; Trimesh 4.6 MiB, embreex 36 MiB) and 787 MiB
for the Open3D environment (Open3D itself 289 MiB plus its broad transitive stack).
Downloaded macOS candidate wheels were 0.75 MiB and 13.2 MiB for Trimesh/embreex,
versus 103.1 MiB for Open3D. The observed Open3D CPython 3.12 Linux x86_64 wheel was
447.7 MiB; the embreex CPython 3.13 Linux x86_64 wheel was 14.5 MiB. Available wheels
require no local compilation on the observed targets.

## Contract feasibility and correctness

The spike exercised a backend-neutral contract with batched normalized origins and
directions, first-hit distance, primitive index, deterministic object ownership,
minimum distance, and optional maximum distance. Trimesh exposes `intersects_first`,
`intersects_any`, `intersects_id`, and `intersects_location`; a deterministic
concatenated mesh permits a face-index-to-canonical-object lookup. Open3D exposes
`cast_rays` and `test_occlusions`, with geometry and primitive IDs directly.

The synthetic review covered: no occluder; two-triangle rectangles; full and partial
blocking; a rotated plane; multiple and disconnected objects; stacked first-hit
objects; parallel and away-pointing rays; close origins; a triangulated grid; and an
arbitrary triangle. Exact edge/vertex rays were excluded because ownership at a
shared mathematical boundary is backend-dependent. Independently calculated
interior hit/miss and first-distance cases agreed for both candidates.

The repository rectangular oracle was evaluated with a 10x10 receiver grid and a
half-width rectangular blocker represented by two triangles. Both candidates matched
all 100 non-edge shaded/unshaded classifications (0 mismatches). The benchmark
script's additional four-ray analytical check also had 0 mismatches for each engine.

Both engines treat triangles as opaque from either side in the tested CPU paths and
support non-watertight/disconnected meshes. Empty-scene behavior should be handled by
the future adapter as an immediate all-miss result rather than asking either engine
to build an empty acceleration structure.

## Numerical observations

Both candidates return a zero-distance hit for an origin exactly on a triangle. A
Trimesh/embreex first query from 1e-8 m below/above returned approximately +1e-8 m
and -1e-8 m; Open3D's float32 ray input rounded both to zero. Candidate APIs therefore
provide enough information for an adapter to enforce positive-distance and source
primitive/object filtering, but S5B must specify that policy and must not rely on raw
`intersects_first` alone. Open3D directly accepts `tnear`/`tfar`; the Trimesh adapter
must filter first-hit distance (and continue past an excluded self-hit where needed).

At the origin and 1 km translation, both engines preserved the expected 9,000 hits
out of 10,000 rays. At a deliberately poor 10,000 km translation, both returned
8,017, demonstrating float32-scale loss. Canonical site recentering remains required;
large global projected coordinates must not be passed directly. Open3D reported a
1 m distance as 0.9999999404 m; embreex reported 1.0 m in the basic case. Parallel and
away-pointing non-edge rays missed as expected.

## Performance evidence

Host: macOS 15.4.1 x86_64, Python 3.11.8, NumPy 2.4.6. Fixed seed: 20260914.
Build time includes the first ray because both engines build acceleration lazily.
Query timings are single observations and are not CI thresholds.

| Backend / scene | Triangles | Build (s) | 10k rays | 100k rays | 1m rays |
|---|---:|---:|---:|---:|---:|
| Trimesh+embreex / small | 100 | 0.00135 | 0.00626 s / 1.60M r/s | 0.08136 s / 1.23M r/s | 0.67333 s / 1.49M r/s |
| Trimesh+embreex / representative | 50,000 | 0.09142 | 0.01710 s / 0.58M r/s | 0.08165 s / 1.22M r/s | 0.87530 s / 1.14M r/s |
| Open3D / small | 100 | 0.00048 | 0.00363 s / 2.76M r/s | 0.02139 s / 4.67M r/s | 0.21701 s / 4.61M r/s |
| Open3D / representative | 50,000 | 0.02477 | 0.00641 s / 1.56M r/s | 0.02474 s / 4.04M r/s | 0.24202 s / 4.13M r/s |

The scene was reused for every ray count. Open3D was roughly 3.6x faster at one
million rays in the representative scene, but cannot currently install on the
project's Python 3.13 CI target and costs hundreds of MiB more in a container.

## Known limitations and S5B boundary

S5B should add reviewed runtime versions of Trimesh and embreex and implement a
Heliotelligence-owned adapter from immutable canonical `TriangleMesh` objects. It
must validate finite batched rays, concatenate eligible meshes deterministically,
retain face-to-object ownership, reuse a static intersector, handle empty scenes,
enforce two-sided positive-hit `t_min`/optional `t_max`, and define self-hit traversal
when the first primitive belongs to the emitting receiver. Tests must repeat the
rectangle-oracle comparison and cover reflections, close occluders, identity, and
bounded rays on Linux/Python 3.13.

The adapter must not decide that `ShadowRole.UNKNOWN` casts shadows, replace analytical
inter-row or terrain-horizon physics, import PVCollada, or expose Trimesh objects as
canonical domain types. S4B PVcase acceptance remains a separate external gate.
