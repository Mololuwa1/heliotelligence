#!/usr/bin/env python3
"""
Single-site PV geometry extraction from an as-built PDF.

STATUS: single-site tool, NOT an automated onboarding pipeline.
Achieved 0.44m mean georeferencing residual on Bracon Ash (site-001).

This script is parameterised by the CONFIG block, but onboarding a NEW
site is NOT plug-and-play. The following must be revisited per site:

  PER-SITE / MANUAL (cannot be automated as-is):
  - CONTROL_POINTS: read off satellite imagery BY HAND. Identify distinct
    features (e.g. transformer stations) in the PDF, find the same features
    on satellite, record both PDF-point and real lat/lon. This is the
    human-confirmation step and is irreducibly manual in this version.
  - MODULE_SIZE_FILTER: tuned to THIS EPC's drawing at THIS scale. A
    different vendor or scale draws modules at different point sizes;
    re-inspect the PDF's path sizes and retune.
  - UTM_EPSG: region-specific. 31N is England; change for other regions.
  - TABLE_COUNTS: from the site's electrical spec.

  GENERALISES (logic is site-agnostic):
  - the transform solver, extraction loop, dedup, clustering, output schema.

TODO (generalisation): the per-site tuning above is what a real onboarding
flow must replace with an ASSISTED step — extract candidate shapes, then let
a human drag/rotate the result over satellite imagery to set the control
points visually. Do NOT attempt that abstraction until this has been run on
a SECOND real site; the second site reveals what actually varies.

Run: python scripts/extract_site_geometry.py
Deps: pymupdf, numpy, pyproj, scikit-learn
"""

# ── CONFIG ─────────────────────────────────────────────────────────────────
# Change the values in this block when running on a new site.
# See module docstring for what is manual vs automatic.

SITE_ID = "site-001"

PDF_PATH = "site_extract/GB-BRA01&CLD301_R00_DRAWING - OVERALL SITE LAYOUT.pdf"

# Ground control points:  label → (pdf_x, pdf_y, real_lat, real_lon)
# pdf_x/y  — centroid of the feature in PDF page coords (y increases DOWN).
# real_lat/lon — satellite-measured WGS84 position of the same feature.
CONTROL_POINTS = {
    "MQA11": (269.3, 346.2, 52.56057626061976,  1.2116907342062098),
    "MQA21": (415.5, 357.5, 52.561962717182034, 1.2119550492725906),
    "MQA22": (623.3, 423.1, 52.56390524587879,  1.213130059547108),
    "MQA23": (623.2, 614.5, 52.56382439319495,  1.2161236977736716),
}

# Number of mounting-table cluster centres to find per inverter group.
# Source: site electrical spec / as-built drawings.
TABLE_COUNTS = {
    "MQA11": 160,
    "MQA21": 160,
    "MQA22": 170,
    "MQA23": 170,
}

# Bounding-rect size filter for module-shaped paths (PDF point units).
# Tuned for this drawing's scale — re-inspect for other EPCs.
MODULE_SIZE_FILTER = {
    "w_min": 1.8, "w_max": 2.4,
    "h_min": 0.9, "h_max": 1.3,
}

UTM_EPSG = 32631  # zone 31N — correct for England; CHANGE per site region

# Abort if mean georeferencing residual exceeds this value (metres).
MAX_RESIDUAL_M = 5.0

# ── END CONFIG ─────────────────────────────────────────────────────────────

import json
import sys
from pathlib import Path

import fitz          # pymupdf
import numpy as np
from pyproj import Transformer
from grid_reconstruct import reconstruct_table_grid


# ── Umeyama similarity transform ───────────────────────────────────────────

def _umeyama(
    src: np.ndarray,
    dst: np.ndarray,
) -> tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    """Solve similarity transform (scale, R, t, src_mean) via Umeyama 1991.

    Finds the least-squares similarity mapping src → dst:
        dst_approx = (src - src_mean) @ R.T * scale + t

    Parameters
    ----------
    src : (N, 2)  source points in PDF coords (Y already flipped)
    dst : (N, 2)  target points in UTM metres

    Returns
    -------
    scale    : float    metres per PDF unit
    R        : (2, 2)   rotation matrix
    t        : (2,)     translation  (equals dst centroid)
    src_mean : (2,)     source centroid (must be subtracted before applying)
    """
    n = len(src)
    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)

    src_c = src - src_mean
    dst_c = dst - dst_mean

    cov = (dst_c.T @ src_c) / n
    U, S, Vt = np.linalg.svd(cov)

    # Correct for reflection if det < 0
    det_sign = np.linalg.det(U @ Vt)
    D = np.diag([1.0, 1.0 if det_sign > 0 else -1.0])

    R = U @ D @ Vt
    src_var = float(np.sum(src_c ** 2) / n)
    scale = float(np.sum(S * np.diag(D)) / src_var)

    # In the centred formulation, t is simply dst_mean
    t = dst_mean

    return scale, R, t, src_mean


def _apply_transform(
    pts: np.ndarray,
    scale: float,
    R: np.ndarray,
    t: np.ndarray,
    src_mean: np.ndarray,
) -> np.ndarray:
    """Apply a precomputed Umeyama transform to an (N, 2) array."""
    return (pts - src_mean) @ R.T * scale + t


# ── PDF extraction ─────────────────────────────────────────────────────────

def extract_module_centroids(pdf_path: str, size_filter: dict) -> np.ndarray:
    """Return (N, 2) array of [x, -y] centroids of module-sized shapes.

    Scans page 0 for closed rectangular paths whose bounding rect falls
    within the configured width/height range.  Y is negated so the
    coordinate system increases northward (required by the Umeyama solver).
    """
    pdf = fitz.open(pdf_path)
    page = pdf[0]
    paths = page.get_drawings()

    w_min, w_max = size_filter["w_min"], size_filter["w_max"]
    h_min, h_max = size_filter["h_min"], size_filter["h_max"]

    pts: list[list[float]] = []
    for p in paths:
        if not p["rect"]:
            continue
        w = p["rect"].width
        h = p["rect"].height
        if w_min <= w <= w_max and h_min <= h <= h_max:
            cx = (p["rect"].x0 + p["rect"].x1) / 2
            cy = (p["rect"].y0 + p["rect"].y1) / 2
            pts.append([cx, -cy])  # flip Y so north is positive

    pdf.close()
    return np.array(pts, dtype=float)


def dedup_centroids(pts: np.ndarray, grid_size: float = 0.2) -> np.ndarray:
    """Remove duplicate points by snapping to a grid of *grid_size* units."""
    keys = (pts / grid_size).round().astype(int)
    _, unique_idx = np.unique(keys, axis=0, return_index=True)
    return pts[unique_idx]


# ── Georeferencing ─────────────────────────────────────────────────────────

def build_transform(
    control_points: dict,
    utm_epsg: int,
) -> tuple[float, np.ndarray, np.ndarray, np.ndarray, Transformer, float]:
    """Solve Umeyama from CONTROL_POINTS, print residuals, abort if too large.

    Returns
    -------
    scale, R, t, src_mean  — transform parameters
    to_wgs                 — Transformer(UTM → WGS84)
    mean_residual_m        — for embedding in output metadata
    """
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)
    to_wgs = Transformer.from_crs(f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True)

    src_pts: list[list[float]] = []
    dst_pts: list[list[float]] = []

    for _label, (px, py, lat, lon) in control_points.items():
        e, n = to_utm.transform(lon, lat)
        src_pts.append([px, -py])  # flip PDF y
        dst_pts.append([e, n])

    src_arr = np.array(src_pts)
    dst_arr = np.array(dst_pts)

    scale, R, t, src_mean = _umeyama(src_arr, dst_arr)

    # Per-point residuals
    pred = _apply_transform(src_arr, scale, R, t, src_mean)
    residuals = np.linalg.norm(pred - dst_arr, axis=1)
    mean_res = float(residuals.mean())

    print("Georeferencing residuals:")
    for label, res in zip(control_points.keys(), residuals):
        flag = "  <-- WARNING" if res > MAX_RESIDUAL_M else ""
        print(f"  {label}: {res:.3f} m{flag}")
    print(f"  mean: {mean_res:.3f} m")

    if mean_res > MAX_RESIDUAL_M:
        sys.exit(
            f"\nERROR: mean residual {mean_res:.2f} m exceeds limit "
            f"{MAX_RESIDUAL_M} m.\n"
            "Check CONTROL_POINTS or MODULE_SIZE_FILTER and re-run."
        )

    return scale, R, t, src_mean, to_wgs, mean_res


# ── Group assignment and table clustering ──────────────────────────────────

def assign_to_groups(
    utm_pts: np.ndarray,
    control_points: dict,
    utm_epsg: int,
) -> np.ndarray:
    """Assign each UTM point to the nearest control-point group centre.

    Returns integer index array (0..N_groups-1).
    """
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)

    centres = []
    for _label, (_, _, lat, lon) in control_points.items():
        e, n = to_utm.transform(lon, lat)
        centres.append([e, n])
    centres_arr = np.array(centres)

    dists = np.sum(
        (utm_pts[:, None, :] - centres_arr[None, :, :]) ** 2, axis=2
    )
    return np.argmin(dists, axis=1)


def reconstruct_tables(utm_pts, control_points, utm_epsg, to_wgs,
                       pitch=6.6, table_w=54.672):
    """Reconstruct mounting tables PER inverter group.

    Per-block reconstruction prevents a global row-lattice from spanning the
    roads between the four physically-separate blocks.

    PCA on an individual block is ambiguous: nearly-square blocks can return
    either the along-row or the across-row axis as the 'major' axis. To resolve
    this, both candidate bearings (pca and pca+90°) are tried; whichever yields
    more table centroids is kept."""
    module_groups = assign_to_groups(utm_pts, control_points, utm_epsg)
    gids = list(control_points.keys())
    out = {}
    for gi, gid in enumerate(gids):
        pts = utm_pts[module_groups == gi]
        if len(pts) < 50:
            print(f"  WARNING: group {gid} has only {len(pts)} modules - skipping")
            continue

        r = reconstruct_table_grid(pts, az_deg=None, pitch=pitch, table_w=table_w)

        mc = r["module_counts"]
        med = int(np.median(mc)) if len(mc) else 0
        print(f"  {gid}: {len(pts)} modules -> {len(r['centroids_EN'])} tables, "
              f"{r['n_rows']} rows, az_used={r['az_used_deg']:.2f}, med_mod/tbl={med}")
        tables = []
        for (e, n), cnt in zip(r["centroids_EN"], mc):
            lon, lat = to_wgs.transform(e, n)
            tables.append({"lon": round(float(lon), 7), "lat": round(float(lat), 7),
                           "module_count": int(cnt)})
        tables.sort(key=lambda x: (x["lat"], x["lon"]))
        if tables:
            out[gid] = tables
    return out


# ── Output schema ──────────────────────────────────────────────────────────

def build_output(
    tables_by_group: dict[str, list[dict]],
    utm_epsg: int,
    total_modules: int,
    mean_residual_m: float,
) -> dict:
    """Build the config/geometry/{site_id}.json payload."""
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)

    groups_out = []
    for gid, tables in tables_by_group.items():
        lons = [t["lon"] for t in tables]
        lats = [t["lat"] for t in tables]
        es, ns = to_utm.transform(lons, lats)

        groups_out.append({
            "id": gid,
            "centre_lat": round(float(np.mean(lats)), 7),
            "centre_lon": round(float(np.mean(lons)), 7),
            "zone_ew_m":  round(float(max(es) - min(es)), 1),
            "zone_ns_m":  round(float(max(ns) - min(ns)), 1),
            "panel_count": len(tables),
            "panels": [[t["lon"], t["lat"]] for t in tables],
        })

    return {
        "_source": PDF_PATH,
        "_georef_residual_m": round(mean_residual_m, 3),
        "_total_modules_extracted": total_modules,
        "groups": groups_out,
    }


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    print(f"=== extract_site_geometry  site={SITE_ID} ===\n")

    # 1. Extract
    print(f"Step 1: Extracting module-shaped paths from PDF ...")
    raw_pts = extract_module_centroids(PDF_PATH, MODULE_SIZE_FILTER)
    print(f"  Found {len(raw_pts)} module-shaped paths")

    dedup_pts = dedup_centroids(raw_pts)
    print(f"  After deduplication: {len(dedup_pts)} unique centroids")

    # 2. Georeference
    print("\nStep 2: Solving Umeyama similarity transform ...")
    scale, R, t, src_mean, to_wgs, mean_res = build_transform(
        CONTROL_POINTS, UTM_EPSG
    )
    rotation_deg = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    print(f"  scale={scale:.4f} m/pt  rotation={rotation_deg:.2f}°")

    utm_pts = _apply_transform(dedup_pts, scale, R, t, src_mean)
    lons, lats = to_wgs.transform(utm_pts[:, 0], utm_pts[:, 1])
    print(f"  Geographic extent:")
    print(f"    lon=[{lons.min():.5f}, {lons.max():.5f}]")
    print(f"    lat=[{lats.min():.5f}, {lats.max():.5f}]")

    # 3. Cluster
    print("\nStep 3: Reconstructing table grid from as-built geometry ...")
    tables_by_group = reconstruct_tables(utm_pts, CONTROL_POINTS, UTM_EPSG, to_wgs)

    # 4. Write output
    output = build_output(tables_by_group, UTM_EPSG, len(dedup_pts), mean_res)

    out_path = Path("config/geometry") / f"{SITE_ID}_run1.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(output, f, indent=2)

    total_tables = sum(len(v) for v in tables_by_group.values())
    print(f"\nStep 4: Written → {out_path}")
    print(f"  Groups   : {list(tables_by_group.keys())}")
    print(f"  Tables   : {[len(v) for v in tables_by_group.values()]}  (total {total_tables})")
    print(f"  Residual : {mean_res:.3f} m")
    print("\nDone.")


if __name__ == "__main__":
    main()
