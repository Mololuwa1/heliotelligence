#!/usr/bin/env python3
"""Mounting-table geometry for Bracon Ash from the as-built DC Cable Plan,
snapped onto the layout-PDF module cloud.

Scope / why:
  The DC Cable Plan draws each table as ~3 string outlines at their as-built
  position and orientation -> the authoritative source for table COUNT, GROUPING
  and ROW BEARING. Its absolute georef (via control points measured on the layout
  PDF) carries a small ~1 m systematic offset, so each table centroid is snapped
  to the mean of the layout-PDF module centroids inside its oriented footprint
  (that cloud is georeferenced at ~0.44 m and is the position reference). The row
  bearing is a single site-wide value (outlines agree to <1 deg), stored top-level
  as row_bearing_deg. Supersedes the grid_reconstruct/reconstruct_tables approach,
  which assumed more row regularity than the site has. Deterministic.
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

import fitz
import numpy as np
from sklearn.cluster import DBSCAN

from extract_site_geometry import (
    build_transform, _apply_transform,
    extract_module_centroids, dedup_centroids,
    assign_to_groups, build_output,
    PDF_PATH, MODULE_SIZE_FILTER, CONTROL_POINTS, UTM_EPSG,
)

# ----------------------------- CONFIG --------------------------------------
CABLE_PLAN_PDF   = "site_extract/GB-BRA01&ETC305_R00_DRAWING - DC CABLE PLAN.pdf"
SITE_ID          = "site-001"
SHAPE_LEN_RANGE  = (24.0, 58.0)   # pdf-unit length of a string outline
SHAPE_ASPECT_MIN = 6.0            # length/width to select elongated outlines
BEARING_INLIER_DEG = 10.0         # keep outlines within this of dominant bearing
CLUSTER_EPS      = 5.0            # m; groups the ~3 outlines of one table
CLUSTER_MIN_SIZE = 2             # drop size-1 singletons
SNAP_HALF_U      = 27.0           # m; half table width along the row
SNAP_HALF_V      = 3.3            # m; half the row pitch, across the row
SNAP_MIN_MODULES = 10             # min modules in footprint to keep a table
OUT_CANDIDATE    = True           # write _regen.json (candidate), not live
# ---------------------------------------------------------------------------


def _shape_geom(drawing):
    pts = []
    for it in drawing.get("items", []):
        op = it[0]
        if op == "l":
            pts += [(it[1].x, -it[1].y), (it[2].x, -it[2].y)]
        elif op == "c":
            pts += [(it[1].x, -it[1].y), (it[-1].x, -it[-1].y)]
        elif op == "re":
            r = it[1]
            pts += [(r.x0,-r.y0),(r.x1,-r.y0),(r.x1,-r.y1),(r.x0,-r.y1)]
    if len(pts) < 2:
        return None
    P = np.array(pts, float); c = P.mean(0); d0 = P - c
    if not np.any(np.abs(d0) > 1e-9):
        return None
    w, v = np.linalg.eigh(np.cov(d0.T))
    return c, v[:, int(np.argmax(w))], float(np.ptp(d0 @ v[:, int(np.argmax(w))])), \
           max(float(np.ptp(d0 @ v[:, int(np.argmin(w))])), 1e-6)


def extract_outlines(pdf_path):
    page = fitz.open(pdf_path)[0]
    cents, dirs = [], []
    for d in page.get_drawings():
        g = _shape_geom(d)
        if g is None:
            continue
        c, major, L, Wd = g
        if SHAPE_LEN_RANGE[0] <= L <= SHAPE_LEN_RANGE[1] and L / Wd >= SHAPE_ASPECT_MIN:
            cents.append(c); dirs.append(major)
    return np.array(cents), np.array(dirs)


def cluster_to_tables(utm_cents):
    lab = DBSCAN(eps=CLUSTER_EPS, min_samples=1).fit_predict(utm_cents)
    hist = dict(sorted(Counter(np.bincount(lab)).items()))
    keep = [b for b in range(lab.max() + 1) if (lab == b).sum() >= CLUSTER_MIN_SIZE]
    return np.array([utm_cents[lab == b].mean(0) for b in keep]), hist


def snap_to_modules(tbl_utm, utm_mod, bearing_deg):
    th = np.radians(bearing_deg); c, s = np.cos(th), np.sin(th)
    origin = utm_mod.mean(0)
    to_local = lambda EN: np.column_stack(
        [(EN-origin)[:,0]*c + (EN-origin)[:,1]*s, -(EN-origin)[:,0]*s + (EN-origin)[:,1]*c])
    mod_l, tbl_l = to_local(utm_mod), to_local(tbl_utm)
    out, cnt = [], []
    for tu, tv in tbl_l:
        m = (np.abs(mod_l[:,0]-tu) <= SNAP_HALF_U) & (np.abs(mod_l[:,1]-tv) <= SNAP_HALF_V)
        k = int(m.sum())
        if k >= SNAP_MIN_MODULES:
            cu, cv = mod_l[m].mean(0)
            out.append((origin[0]+c*cu - s*cv, origin[1]+s*cu + c*cv)); cnt.append(k)
    return np.array(out), np.array(cnt)


def main():
    print(f"=== extract_tables_from_cable_plan  site={SITE_ID} ===")
    scale, R, t, src_mean, to_wgs, mean_res = build_transform(CONTROL_POINTS, UTM_EPSG)

    cents_pdf, dirs_pdf = extract_outlines(CABLE_PLAN_PDF)
    utm_cents = _apply_transform(cents_pdf, scale, R, t, src_mean)
    bear = np.degrees(np.arctan2((dirs_pdf @ R.T)[:,1], (dirs_pdf @ R.T)[:,0])) % 180.0
    dom = float(np.median(bear))
    inl = np.abs(((bear - dom + 90) % 180) - 90) <= BEARING_INLIER_DEG
    utm_cents = utm_cents[inl]
    print(f"outlines: {len(cents_pdf)}  inliers: {int(inl.sum())}  bearing={dom:.2f}")

    tbl, hist = cluster_to_tables(utm_cents)
    print(f"cluster-size histogram: {hist}")
    print(f"table centroids (clustered): {len(tbl)}")

    raw = extract_module_centroids(PDF_PATH, MODULE_SIZE_FILTER)
    utm_mod = _apply_transform(dedup_centroids(raw), scale, R, t, src_mean)
    snapped, counts = snap_to_modules(tbl, utm_mod, dom)
    print(f"snapped tables: {len(snapped)}  (dropped {len(tbl)-len(snapped)})")
    print(f"modules/table: median={int(np.median(counts))}  min={counts.min()}  max={counts.max()}")

    gi = assign_to_groups(snapped, CONTROL_POINTS, UTM_EPSG)
    gids = list(CONTROL_POINTS.keys()); tbg = {g: [] for g in gids}
    for (e, n), g, k in zip(snapped, gi, counts):
        lon, lat = to_wgs.transform(e, n)
        tbg[gids[g]].append({"lon": round(float(lon),7), "lat": round(float(lat),7), "module_count": int(k)})
    tbg = {g: v for g, v in tbg.items() if v}
    print("per-group:", {g: len(v) for g, v in tbg.items()}, " total", sum(len(v) for v in tbg.values()))

    out = build_output(tbg, UTM_EPSG, len(utm_mod), mean_res)
    out["_source"] = f"{CABLE_PLAN_PDF} (structure) + {PDF_PATH} (positions)"
    out["row_bearing_deg"] = round(dom, 2)
    out_path = Path("config/geometry") / f"{SITE_ID}{'_regen' if OUT_CANDIDATE else ''}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, out_path.open("w"), indent=2)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
