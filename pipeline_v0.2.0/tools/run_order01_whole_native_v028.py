from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen
from datetime import datetime, timezone
from dataclasses import fields
import ast, base64, csv, gzip, hashlib, json, math, subprocess, sys, time

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, search_around_sky
from astropy.io import fits
from astropy.wcs import WCS

from transient_pipeline.config import FrozenMethod
from transient_pipeline.detector import detect_array

ROOT = Path.cwd()
ORDER = 1
POSS_ID, REGION, POSS_PLATE, DASCH_PLATE = "POSS-I:413:E:rec297", "XE296", "06S2", "ai43437"

CORE, HALO, DASCH_BOUND_PAD, GEOM_GRID = 1024, 64, 256, 65

DETECTOR = ROOT / "src/transient_pipeline/detector.py"
METHOD = ROOT / "config/frozen_method.json"
PAIRMAP = ROOT / "research/SUB5_V028_POSS_PAIR_EXECUTION_MAP_2026-08-21.csv"
GEOM_SOURCE = ROOT / "tools/repair_remaining_poss_geometry_v028.py"
CONTROL_SOURCE = ROOT / "tools/run_pair61_native_detector_control_v028.py"
REF = ROOT / "cache/poss1_identity/POSS-I_413_E_rec297/06S2_identity.fits"
POLICY = ROOT / "research/NATIVE_TILE_EXECUTION_POLICY_V028_2026-08-21.json"

WORK = ROOT / "work/order01_native_full_v028"
RESULT = ROOT / "results/order01_native_full_v028"
POSS_DIR, DASCH_DIR = WORK / "poss_tiles", WORK / "dasch_tiles"
for d in (WORK, RESULT, POSS_DIR, DASCH_DIR):
    d.mkdir(parents=True, exist_ok=True)

EXPECTED_DETECTOR_SHA = "709da8d7a7972b15808d70a1e4dbffa0fd0fee864a81d954f74fe4a5f5af25e7"
EXPECTED_METHOD_SHA = "2cb3cabd573d7af99399899f2ccecd3002be90297e55bb0e0dcdd9dea1d0c4c1"
EXPECTED_JAR_SHA = "8483a20d986bb61fa1d733ce16d446fb2a0ff363bc1b1367e28b01a1bbdcbb8d"

API = "https://api.starglass.cfa.harvard.edu/public/dasch/dr7/mosaic_package"
UA = "historical-transient-pipeline/0.2.8-order01-whole-pair"
POSS_RAW = "https://skyview.gsfc.nasa.gov/surveys/dss/xe296"

CAND_FIELDS = [
    "tile_id", "candidate_index", "local_x", "local_y", "global_x", "global_y",
    "ra_deg", "dec_deg", "snr", "signal", "polarity", "sigma",
]
MATCH_FIELDS = [
    "match_index", "separation_arcsec", "strict_le_3arcsec",
    "poss_tile_id", "poss_candidate_index", "poss_ra_deg", "poss_dec_deg",
    "poss_snr", "poss_polarity", "dasch_tile_id", "dasch_candidate_index",
    "dasch_ra_deg", "dasch_dec_deg", "dasch_snr", "dasch_polarity",
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def arr_sha(a: np.ndarray) -> str:
    a = np.ascontiguousarray(a)
    h = hashlib.sha256()
    h.update(str(a.dtype).encode())
    h.update(repr(tuple(map(int, a.shape))).encode())
    h.update(a.tobytes())
    return h.hexdigest()


def jdefault(o):
    if isinstance(o, np.generic): return o.item()
    if isinstance(o, np.ndarray): return o.tolist()
    if isinstance(o, Path): return str(o)
    return str(o)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=jdefault) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_csv(path: Path, rows: list[dict], fields_: list[str]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields_, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def load_functions(path: Path, names: tuple[str, ...], namespace: dict):
    text = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(text, filename=str(path))
    nodes = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names
    ]
    if {n.name for n in nodes} != set(names):
        raise RuntimeError(f"REFUSING: could not recover {names} uniquely from {path}")
    mod = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = dict(namespace)
    exec(compile(mod, str(path), "exec"), ns, ns)
    return tuple(ns[n] for n in names)


def load_java_constant(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    vals = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "JAVA" for t in node.targets):
            vals.append(ast.literal_eval(node.value))
    if len(vals) != 1 or not isinstance(vals[0], str):
        raise RuntimeError("REFUSING: validated JAVA extractor was not uniquely recoverable")
    return vals[0]


def guard_method():
    if sha_file(DETECTOR) != EXPECTED_DETECTOR_SHA:
        raise RuntimeError("REFUSING: frozen detector SHA changed")
    if sha_file(METHOD) != EXPECTED_METHOD_SHA:
        raise RuntimeError("REFUSING: frozen method SHA changed")

    cfg = json.loads(METHOD.read_text(encoding="utf-8"))
    valid = {f.name for f in fields(FrozenMethod)}
    if set(cfg) - valid:
        raise RuntimeError(f"REFUSING: unknown frozen method keys {sorted(set(cfg)-valid)}")
    m = FrozenMethod(**cfg)

    expected = {
        "background_sigma_px": 8.0, "peak_sigma": 4.0, "max_window_px": 7,
        "edge_px": 30, "diagnostic_match_arcsec": 10.0,
        "strict_registered_match_arcsec": 3.0,
    }
    for k, v in expected.items():
        if getattr(m, k) != v:
            raise RuntimeError(f"REFUSING: frozen method changed at {k}")
    return m, cfg


def freeze_policy() -> str:
    obj = {
        "policy_id": "native_tile_execution_v028",
        "fixed_before_complete_order61_footprint_outcome": True,
        "note_order61_central_control_already_seen": True,
        "detector_unit": "native archive pixel tile",
        "no_resampling": True,
        "core_px": CORE,
        "halo_px": HALO,
        "grid_anchor_full_scan_zero_based_px": [0, 0],
        "edge_tiles": "clip halo to physical scan; frozen detector edge mask remains active",
        "candidate_acceptance": "non-overlapping core only",
        "robust_sigma_scope": "each native extracted tile including halo",
        "poss_astrometry": "validated GSSS DSS polynomial; P1/P2 = zero_based_full_pixel + 1.5",
        "dasch_astrometry": "DR7 direct TPV b01HeaderGz in value-added rotated mosaic orientation",
        "crossmatch_diagnostic_arcsec": 10.0,
        "crossmatch_strict_arcsec": 3.0,
        "no_retuning_from_candidate_yield": True,
    }
    canonical = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    if POLICY.exists():
        if POLICY.read_text(encoding="utf-8") != canonical:
            raise RuntimeError("REFUSING: existing native-tile execution policy differs")
    else:
        POLICY.write_text(canonical, encoding="utf-8")
    return sha_file(POLICY)


def pair_row():
    with PAIRMAP.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    hits = [r for r in rows if int(float(r["canonical_order"])) == ORDER]
    if len(hits) != 1:
        raise RuntimeError(f"REFUSING: order01 row count={len(hits)}")
    r = hits[0]
    for k, v in {
        "poss_exposure_id": POSS_ID,
        "poss_region": REGION,
        "partner_dasch_plate_id": DASCH_PLATE,
    }.items():
        if r.get(k) != v:
            raise RuntimeError(f"REFUSING: order01 {k}={r.get(k)!r}, expected {v!r}")
    if float(r["actual_overlap_s"]) <= 0:
        raise RuntimeError("REFUSING: non-positive actual exposure overlap")
    return r


def find_jar():
    """
    Resolve the exact SkyView JAR already validated by the
    completed pair-61 native-detector control.

    The prior control report is authoritative provenance.
    Recursive discovery is retained only as a guarded fallback.
    """

    control_report = (
        ROOT
        / "results"
        / "pair61_native_detector_control_v028"
        / "pair61_native_detector_control_report.json"
    )

    if control_report.is_file():
        report = json.loads(
            control_report.read_text(
                encoding="utf-8"
            )
        )

        recorded_path = str(
            report.get(
                "skyview_jar",
                ""
            )
        ).strip()

        recorded_sha = str(
            report.get(
                "skyview_jar_sha256",
                ""
            )
        ).strip().lower()

        if recorded_sha:
            if recorded_sha != EXPECTED_JAR_SHA:
                raise RuntimeError(
                    "REFUSING: prior pair61 report "
                    "records an unexpected SkyView "
                    f"JAR SHA: {recorded_sha}"
                )

        if recorded_path:
            candidate = Path(
                recorded_path
            )

            if not candidate.is_absolute():
                candidate = (
                    ROOT
                    / candidate
                )

            if candidate.is_file():
                actual = sha_file(
                    candidate
                )

                if actual != EXPECTED_JAR_SHA:
                    raise RuntimeError(
                        "REFUSING: previously validated "
                        "SkyView JAR path now has a "
                        "different SHA256: "
                        f"{candidate} -> {actual}"
                    )

                print(
                    "SkyView JAR recovered from "
                    "validated pair61 report:",
                    candidate,
                )

                return candidate

    # Guarded fallback only.
    scanned = []

    for candidate in ROOT.rglob(
        "*.jar"
    ):
        try:
            actual = sha_file(
                candidate
            )

            scanned.append(
                (
                    candidate,
                    actual,
                )
            )

            if actual == EXPECTED_JAR_SHA:
                print(
                    "SkyView JAR recovered by "
                    "fallback hash discovery:",
                    candidate,
                )

                return candidate

        except OSError:
            pass

    detail = "\n".join(
        f"  {path} -> {digest}"
        for path, digest
        in scanned[:25]
    )

    raise RuntimeError(
        "REFUSING: validated SkyView JAR "
        "not found.\n"
        f"JAR files scanned: {len(scanned)}"
        + (
            "\n" + detail
            if detail
            else ""
        )
    )


def compile_java(jar: Path, source: str):
    src = WORK / "DSSNativeExtract.java"
    src.write_text(source, encoding="utf-8")
    cp = subprocess.run(["javac", "-cp", str(jar), str(src)], capture_output=True, text=True, timeout=120)
    if cp.returncode:
        raise RuntimeError("javac failed:\n" + cp.stdout + "\n" + cp.stderr)
    if not (WORK / "DSSNativeExtract.class").exists():
        raise RuntimeError("REFUSING: Java extractor class missing after javac")


def package():
    req = Request(
        API,
        data=json.dumps({"plate_id": DASCH_PLATE, "binning": 1}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA},
        method="POST",
    )
    with urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def geometry_sig(pkg):
    a, m = pkg["metadata"]["astrometry"], pkg["metadata"]["mosaic"]
    obj = {
        "b01HeaderGz": a["b01HeaderGz"], "rotationDelta": a.get("rotationDelta"),
        "b01Height": int(m["b01Height"]), "b01Width": int(m["b01Width"]),
    }
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def output_rect_to_base(k, H, W, ox0, ox1, oy0, oy1):
    if k == 0:  return oy0, oy1, ox0, ox1
    if k == -1: return H-ox1, H-ox0, oy0, oy1
    if k == 1:  return ox0, ox1, W-oy1, W-oy0
    if k == 2:  return H-oy1, H-oy0, W-ox1, W-ox0
    raise RuntimeError(k)


def validate_rect_mapping(validated_base_slice):
    H, W = 130, 170
    base = np.arange(H*W).reshape(H, W)
    for k in (0, -1, 1, 2):
        out = np.rot90(base, k=k)
        oh, ow = out.shape
        n = 20
        ox0, oy0 = min(30, ow-n-1), min(40, oh-n-1)
        ox1, oy1 = ox0+n, oy0+n

        generic = output_rect_to_base(k, H, W, ox0, ox1, oy0, oy1)
        frozen = tuple(validated_base_slice(ox0, oy0, n, k, H, W))
        if generic != frozen:
            raise RuntimeError(f"REFUSING: rectangle mapper disagrees with validated base_slice for k={k}")

        by0, by1, bx0, bx1 = generic
        got = np.rot90(base[by0:by1, bx0:bx1], k=k)
        want = out[oy0:oy1, ox0:ox1]
        if not np.array_equal(got, want):
            raise RuntimeError(f"REFUSING: rectangle mapper fails np.rot90 control for k={k}")


def validate_reference(dss_world):
    if not REF.is_file():
        raise RuntimeError(f"REFUSING: validated reference missing: {REF}")
    h = fits.getheader(REF, 0)
    if str(h.get("REGION", "")).strip().upper() != REGION:
        raise RuntimeError("REFUSING: reference REGION changed")
    if str(h.get("PLATEID", "")).strip().upper() != POSS_PLATE:
        raise RuntimeError("REFUSING: reference PLATEID changed")

    rw = WCS(h).celestial
    errs = []
    for lx, ly in [(0.,0.), (88.,88.), (176.,0.), (0.,176.), (176.,176.)]:
        s1 = rw.pixel_to_world(lx, ly)
        gx, gy = lx + float(h["CNPIX1"]) - 1.0, ly + float(h["CNPIX2"]) - 1.0
        ra, dec = dss_world(h, gx+1.5, gy+1.5)
        s2 = SkyCoord(float(np.asarray(ra))*u.deg, float(np.asarray(dec))*u.deg)
        errs.append(float(s1.separation(s2).arcsec))
    if max(errs) > 0.1:
        raise RuntimeError(f"REFUSING: GSSS/local WCS max error={max(errs):.6f}\"")

    fw, fh = int(h.get("XPIXELS", 14000)), int(h.get("YPIXELS", 13999))
    if (fw, fh) != (14000, 13999):
        raise RuntimeError(f"REFUSING: unexpected XE296 full shape {fw}x{fh}")
    return h, fw, fh, max(errs)


def core_specs(width, height, prefix):
    out = []
    for y0 in range(0, height, CORE):
        for x0 in range(0, width, CORE):
            x1, y1 = min(x0+CORE, width), min(y0+CORE, height)
            out.append({
                "tile_id": f"{prefix}_x{x0:05d}-{x1:05d}_y{y0:05d}-{y1:05d}",
                "x0": x0, "x1": x1, "y0": y0, "y1": y1,
            })
    return out


def checkpoint_valid(meta_path, policy_sha):
    if not meta_path.is_file():
        return False
    try:
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        if not m.get("complete"): return False
        if m.get("policy_sha256") != policy_sha: return False
        if m.get("detector_sha256") != EXPECTED_DETECTOR_SHA: return False
        if m.get("method_sha256") != EXPECTED_METHOD_SHA: return False
        npy, csvp = ROOT/m["npy_path"], ROOT/m["candidates_csv"]
        return (
            npy.is_file() and csvp.is_file()
            and sha_file(npy) == m["npy_file_sha256"]
            and sha_file(csvp) == m["candidates_csv_sha256"]
        )
    except Exception:
        return False


def run_poss_tile(spec, java_cp, h, dss_world, method, policy_sha):
    tid, meta = spec["tile_id"], POSS_DIR/f"{spec['tile_id']}.json"
    if checkpoint_valid(meta, policy_sha):
        return "cached", json.loads(meta.read_text(encoding="utf-8"))

    cx0,cx1,cy0,cy1 = spec["x0"],spec["x1"],spec["y0"],spec["y1"]
    fw, fh = int(h.get("XPIXELS", 14000)), int(h.get("YPIXELS", 13999))
    ex0,ex1 = max(0,cx0-HALO), min(fw,cx1+HALO)
    ey0,ey1 = max(0,cy0-HALO), min(fh,cy1+HALO)
    ew, eh = ex1-ex0, ey1-ey0

    rawbin, npyp, csvp = POSS_DIR/f"{tid}.i32be.bin", POSS_DIR/f"{tid}.npy", POSS_DIR/f"{tid}_candidates.csv"
    cp = subprocess.run(
        ["java","-cp",java_cp,"DSSNativeExtract",POSS_RAW,str(ex0),str(ey0),str(ew),str(eh),str(rawbin)],
        capture_output=True, text=True, timeout=180,
    )
    if cp.returncode:
        raise RuntimeError("POSS native extraction failed:\n"+cp.stdout+"\n"+cp.stderr)
    if not rawbin.is_file() or rawbin.stat().st_size != ew*eh*4:
        raise RuntimeError("POSS native byte-count mismatch")

    arr = np.fromfile(rawbin, dtype=">i4").reshape(eh,ew).astype(np.int32, copy=False)
    np.save(npyp, arr)
    rawbin.unlink(missing_ok=True)

    det = detect_array(arr, method)
    x,y = np.asarray(det["x"],int), np.asarray(det["y"],int)
    gx,gy = ex0+x, ey0+y
    ii = np.flatnonzero((gx>=cx0)&(gx<cx1)&(gy>=cy0)&(gy<cy1))
    if len(ii):
        ra,dec = dss_world(h, gx[ii].astype(float)+1.5, gy[ii].astype(float)+1.5)
        ra,dec = np.asarray(ra,float), np.asarray(dec,float)
    else:
        ra,dec = np.array([]),np.array([])

    rows = [{
        "tile_id":tid, "candidate_index":oi, "local_x":int(x[j]), "local_y":int(y[j]),
        "global_x":int(gx[j]), "global_y":int(gy[j]), "ra_deg":float(ra[oi]),
        "dec_deg":float(dec[oi]), "snr":float(det["snr"][j]), "signal":float(det["signal"][j]),
        "polarity":int(det["polarity"][j]), "sigma":float(det["sigma"]),
    } for oi,j in enumerate(ii)]
    write_csv(csvp, rows, CAND_FIELDS)

    m = {
        "complete":True, "archive":"POSS-I", "plate":POSS_ID, "region":REGION, "tile_id":tid,
        "core":[cx0,cx1,cy0,cy1], "extended":[ex0,ex1,ey0,ey1], "shape":[eh,ew],
        "dtype":str(arr.dtype), "array_sha256":arr_sha(arr), "npy_path":rel(npyp),
        "npy_file_sha256":sha_file(npyp), "candidates_csv":rel(csvp),
        "candidates_csv_sha256":sha_file(csvp), "all_detector_peaks":int(len(x)),
        "accepted_core_peaks":int(len(rows)), "robust_sigma":float(det["sigma"]),
        "median_residual":float(det["median_residual"]), "policy_sha256":policy_sha,
        "detector_sha256":EXPECTED_DETECTOR_SHA, "method_sha256":EXPECTED_METHOD_SHA,
        "java_stderr":cp.stderr.strip(), "completed_at_utc":datetime.now(timezone.utc).isoformat(),
    }
    write_json(meta, m)
    return "done", m


def run_dasch_tile(spec, dw, rk, base_shape, output_shape, geom_sig, method, policy_sha):
    tid, meta = spec["tile_id"], DASCH_DIR/f"{spec['tile_id']}.json"
    if checkpoint_valid(meta, policy_sha):
        return "cached", json.loads(meta.read_text(encoding="utf-8"))

    cx0,cx1,cy0,cy1 = spec["x0"],spec["x1"],spec["y0"],spec["y1"]
    outH,outW = output_shape
    ex0,ex1 = max(0,cx0-HALO), min(outW,cx1+HALO)
    ey0,ey1 = max(0,cy0-HALO), min(outH,cy1+HALO)
    ew,eh = ex1-ex0, ey1-ey0

    pkg = package()
    if geometry_sig(pkg) != geom_sig:
        raise RuntimeError("REFUSING: DASCH geometry metadata changed")
    H,W = base_shape
    by0,by1,bx0,bx1 = output_rect_to_base(rk,H,W,ex0,ex1,ey0,ey1)

    with fits.open(
        pkg["baseFitsUrl"], use_fsspec=True, lazy_load_hdus=True,
        fsspec_kwargs={"block_size":4*1024*1024,"cache_type":"readahead"},
    ) as hdul:
        q = [(i,hdu) for i,hdu in enumerate(hdul)
             if getattr(hdu,"shape",None) and tuple(map(int,hdu.shape))==(H,W)]
        if len(q) != 1:
            raise RuntimeError(f"REFUSING: expected one DASCH image HDU; found {len(q)}")
        hi,hdu = q[0]
        base = np.asarray(hdu.section[by0:by1,bx0:bx1])
        arr = np.rot90(base,k=rk)
        comp = getattr(hdu,"compression_type",None)
        tshape = tuple(int(v) for v in (getattr(hdu,"tile_shape",()) or ()))
        hclass = type(hdu).__name__

    if arr.shape != (eh,ew):
        raise RuntimeError(f"REFUSING: rotated DASCH shape {arr.shape} != {(eh,ew)}")
    if not np.issubdtype(arr.dtype,np.integer):
        vals=arr[np.isfinite(arr)]
        if np.any(np.abs(vals-np.rint(vals))>1e-12):
            raise RuntimeError("REFUSING: non-integer DASCH bin1 pixels")

    npyp,csvp = DASCH_DIR/f"{tid}.npy", DASCH_DIR/f"{tid}_candidates.csv"
    np.save(npyp,arr)
    det=detect_array(arr,method)
    x,y=np.asarray(det["x"],int),np.asarray(det["y"],int)
    gx,gy=ex0+x,ey0+y
    ii=np.flatnonzero((gx>=cx0)&(gx<cx1)&(gy>=cy0)&(gy<cy1))
    if len(ii):
        sky=dw.pixel_to_world(gx[ii].astype(float),gy[ii].astype(float))
        ra,dec=np.asarray(sky.ra.deg,float),np.asarray(sky.dec.deg,float)
    else:
        ra,dec=np.array([]),np.array([])

    rows=[{
        "tile_id":tid,"candidate_index":oi,"local_x":int(x[j]),"local_y":int(y[j]),
        "global_x":int(gx[j]),"global_y":int(gy[j]),"ra_deg":float(ra[oi]),
        "dec_deg":float(dec[oi]),"snr":float(det["snr"][j]),"signal":float(det["signal"][j]),
        "polarity":int(det["polarity"][j]),"sigma":float(det["sigma"]),
    } for oi,j in enumerate(ii)]
    write_csv(csvp,rows,CAND_FIELDS)

    m={
        "complete":True,"archive":"DASCH","plate":DASCH_PLATE,"tile_id":tid,
        "core":[cx0,cx1,cy0,cy1],"extended":[ex0,ex1,ey0,ey1],
        "output_shape":[outH,outW],"base_shape":[H,W],"base_slice":[by0,by1,bx0,bx1],
        "rotation_k":rk,"shape":[eh,ew],"dtype":str(arr.dtype),"array_sha256":arr_sha(arr),
        "npy_path":rel(npyp),"npy_file_sha256":sha_file(npyp),"candidates_csv":rel(csvp),
        "candidates_csv_sha256":sha_file(csvp),"all_detector_peaks":int(len(x)),
        "accepted_core_peaks":int(len(rows)),"robust_sigma":float(det["sigma"]),
        "median_residual":float(det["median_residual"]),"remote_object_bytes":int(pkg["baseFitsSize"]),
        "hdu_index":int(hi),"hdu_class":hclass,"compression":comp,"compression_tile":tshape,
        "geometry_signature":geom_sig,"policy_sha256":policy_sha,
        "detector_sha256":EXPECTED_DETECTOR_SHA,"method_sha256":EXPECTED_METHOD_SHA,
        "completed_at_utc":datetime.now(timezone.utc).isoformat(),
    }
    write_json(meta,m)
    return "done",m


def retries(label, fn, attempts=3):
    errs=[]
    for a in range(1,attempts+1):
        try:
            return fn()
        except Exception as exc:
            errs.append({"attempt":a,"error":repr(exc),"at_utc":datetime.now(timezone.utc).isoformat()})
            print(f"    {label} attempt {a}/{attempts} FAILED: {exc}",flush=True)
            if a<attempts: time.sleep(2**a)
    return "failed",{"errors":errs}


def load_rows(metas):
    out=[]
    for m in metas:
        with (ROOT/m["candidates_csv"]).open(newline="",encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.append({
                    "tile_id":r["tile_id"],"candidate_index":int(r["candidate_index"]),
                    "local_x":int(r["local_x"]),"local_y":int(r["local_y"]),
                    "global_x":int(r["global_x"]),"global_y":int(r["global_y"]),
                    "ra_deg":float(r["ra_deg"]),"dec_deg":float(r["dec_deg"]),
                    "snr":float(r["snr"]),"signal":float(r["signal"]),
                    "polarity":int(r["polarity"]),"sigma":float(r["sigma"]),
                })
    return out


def crossmatch(p,d,m):
    if not p or not d: return []
    ps=SkyCoord([r["ra_deg"] for r in p]*u.deg,[r["dec_deg"] for r in p]*u.deg)
    ds=SkyCoord([r["ra_deg"] for r in d]*u.deg,[r["dec_deg"] for r in d]*u.deg)
    ip,id_,sep,_=search_around_sky(ps,ds,m.diagnostic_match_arcsec*u.arcsec)
    out=[]
    for z in np.argsort(sep.arcsec):
        a,b,s=p[int(ip[z])],d[int(id_[z])],float(sep.arcsec[z])
        out.append({
            "match_index":len(out),"separation_arcsec":s,
            "strict_le_3arcsec":s<=m.strict_registered_match_arcsec,
            "poss_tile_id":a["tile_id"],"poss_candidate_index":a["candidate_index"],
            "poss_ra_deg":a["ra_deg"],"poss_dec_deg":a["dec_deg"],
            "poss_snr":a["snr"],"poss_polarity":a["polarity"],
            "dasch_tile_id":b["tile_id"],"dasch_candidate_index":b["candidate_index"],
            "dasch_ra_deg":b["ra_deg"],"dasch_dec_deg":b["dec_deg"],
            "dasch_snr":b["snr"],"dasch_polarity":b["polarity"],
        })
    return out


def guard_order01_exact_source_preflight():
    p = (
        ROOT / "results" / "order01_native_preflight_v028"
        / "order01_exact_native_source_and_dasch_metadata_v028.json"
    )
    if not p.is_file():
        raise RuntimeError(
            f"REFUSING: Order-1 exact native-source preflight missing: {p}"
        )

    obj = json.loads(p.read_text(encoding="utf-8"))
    if obj.get("status") != "COMPLETE":
        raise RuntimeError(
            "REFUSING: Order-1 exact native-source preflight is not COMPLETE"
        )

    pair = obj["frozen_pair_map_row"]
    src = obj["poss_native_source"]
    ref = obj["frozen_poss_identity_fits"]
    dp = obj["dasch_mosaic_package"]

    checks = {
        "canonical_order": int(float(pair["canonical_order"])) == 1,
        "poss_id": pair["poss_exposure_id"] == POSS_ID,
        "region": pair["poss_region"] == REGION,
        "plate_id": ref["plate_id"] == POSS_PLATE,
        "dasch": pair["partner_dasch_plate_id"].lower() == DASCH_PLATE,
        "overlap": abs(float(pair["actual_overlap_s"]) - 3480.0) < 1e-6,
        "fits_sha": ref["sha256"].lower()
            == "6e8ca42e82804615316845436c934d0b184a5deddeeee9ab0c6951736088fa16",
        "raw_dir": src["raw_plate_directory"].rstrip("/") == POSS_RAW,
        "hhh_sha": src["hhh_sha256"].lower()
            == "e7fce1b323623e4bb6a82e16537cb3728e620870a4a64d36bdc05b05756b37d2",
        "hhh_region": src["hhh_identity"]["region"].upper() == REGION,
        "hhh_plate": src["hhh_identity"]["plate_id"].upper() == POSS_PLATE,
        "hhh_width": int(src["hhh_header_parse"]["selected_header"]["XPIXELS"]) == 14000,
        "hhh_height": int(src["hhh_header_parse"]["selected_header"]["YPIXELS"]) == 13999,
        "dasch_base_url": bool(dp.get("baseFitsUrl")),
        "dasch_metadata": dp.get("metadata") is not None,
        "preflight_no_detector": obj.get("detector_rerun") is False,
        "preflight_no_poss_pixels": obj.get("native_science_pixels_read") is False,
        "preflight_no_dasch_pixels": obj.get("dasch_science_pixels_read") is False,
    }
    if not all(checks.values()):
        raise RuntimeError(
            "REFUSING: Order-1 exact-source preflight guard failed: "
            + repr(checks)
        )
    return obj

def main():
    order01_preflight = guard_order01_exact_source_preflight()
    print("Order-1 exact native-source preflight guard: PASS")
    print("="*88)
    print("ORDER 01 — RESUMABLE WHOLE-FOOTPRINT NATIVE DETECTOR EXECUTION")
    print("="*88)
    print("Frozen detector; native pixels; 1024px non-overlapping core + 64px halo.")
    print("Valid completed tiles are checkpointed and skipped on rerun.\n")

    method,method_cfg=guard_method()
    policy_sha=freeze_policy()
    row=pair_row()
    print("Frozen detector/method: PASS")
    print("Execution policy SHA256:",policy_sha)
    print("Pair identity: PASS")
    print(f"Actual overlap: {float(row['actual_overlap_s']):.3f} s ({float(row['actual_overlap_s'])/60:.3f} min)\n")

    plate_center_radians,dss_world=load_functions(GEOM_SOURCE,("plate_center_radians","dss_world"),{"np":np})
    tpv,base_slice=load_functions(CONTROL_SOURCE,("tpv","base_slice"),{"fits":fits,"WCS":WCS,"gzip":gzip,"base64":base64})
    _=plate_center_radians
    validate_rect_mapping(base_slice)

    h,fw,fh,gerr=validate_reference(dss_world)
    print(f"Exact POSS GSSS/local-WCS control: PASS (max {gerr:.6f}\")")
    print(f"POSS full shape: {fw} x {fh}")

    jar=find_jar()
    compile_java(jar,load_java_constant(CONTROL_SOURCE))
    jsep=";" if sys.platform.startswith("win") else ":"
    java_cp=str(WORK)+jsep+str(jar)
    print("Validated SkyView native extractor: PASS\n")

    print("Resolving DASCH bin1 TPV geometry ...",flush=True)
    first=package()
    gsig=geometry_sig(first)
    dw,dh,rk,base_shape=tpv(first["metadata"])
    H,W=base_shape
    outH,outW=(W,H) if rk in (-1,1) else (H,W)
    print(f"DASCH base/output: {W}x{H} -> {outW}x{outH}; rotation k={rk}")

    xs=np.linspace(0,fw-1,GEOM_GRID)
    ys=np.linspace(0,fh-1,GEOM_GRID)
    gx,gy=np.meshgrid(xs,ys)
    ra,dec=dss_world(h,gx.ravel()+1.5,gy.ravel()+1.5)
    sky=SkyCoord(np.asarray(ra,float)*u.deg,np.asarray(dec,float)*u.deg)
    dx,dy=map(lambda a:np.asarray(a,float),dw.world_to_pixel(sky))
    if not np.all(np.isfinite(dx)&np.isfinite(dy)):
        raise RuntimeError("REFUSING: non-finite POSS->DASCH geometry grid")
    if not np.all((dx>=0)&(dx<outW)&(dy>=0)&(dy<outH)):
        raise RuntimeError("REFUSING: full dense POSS grid no longer lies inside DASCH")

    bx0=max(0,int(math.floor(dx.min()))-DASCH_BOUND_PAD)
    bx1=min(outW,int(math.ceil(dx.max()))+1+DASCH_BOUND_PAD)
    by0=max(0,int(math.floor(dy.min()))-DASCH_BOUND_PAD)
    by1=min(outH,int(math.ceil(dy.max()))+1+DASCH_BOUND_PAD)
    print("Dense 65x65 POSS footprint inside DASCH: PASS")
    print(f"DASCH padded acquisition bbox: x={bx0}:{bx1}, y={by0}:{by1}\n")

    pspec=core_specs(fw,fh,"P")
    dspec=[s for s in core_specs(outW,outH,"D")
           if s["x1"]>bx0 and s["x0"]<bx1 and s["y1"]>by0 and s["y0"]<by1]
    print(f"POSS tiles: {len(pspec)} | DASCH tiles intersecting padded POSS footprint: {len(dspec)}\n")

    failures=[]; pmeta=[]
    for i,s in enumerate(pspec,1):
        status,m=retries(s["tile_id"],lambda s=s:run_poss_tile(s,java_cp,h,dss_world,method,policy_sha))
        if status=="failed":
            failures.append({"archive":"POSS-I","tile_id":s["tile_id"],**m})
            print(f"[POSS {i:03d}/{len(pspec):03d}] FAILED after retries",flush=True)
        else:
            pmeta.append(m)
            print(f"[POSS {i:03d}/{len(pspec):03d}] {status.upper():6s} accepted={m['accepted_core_peaks']:5d} sigma={m['robust_sigma']:.4g}",flush=True)

    print("\nPOSS phase complete.\n")
    dmeta=[]
    for i,s in enumerate(dspec,1):
        status,m=retries(s["tile_id"],lambda s=s:run_dasch_tile(s,dw,rk,base_shape,(outH,outW),gsig,method,policy_sha))
        if status=="failed":
            failures.append({"archive":"DASCH","tile_id":s["tile_id"],**m})
            print(f"[DASCH {i:03d}/{len(dspec):03d}] FAILED after retries",flush=True)
        else:
            dmeta.append(m)
            print(f"[DASCH {i:03d}/{len(dspec):03d}] {status.upper():6s} accepted={m['accepted_core_peaks']:5d} sigma={m['robust_sigma']:.4g}",flush=True)

    failure_path=RESULT/"tile_failures.json"
    write_json(failure_path,failures)

    if failures:
        write_json(RESULT/"order61_incomplete_report.json",{
            "status":"INCOMPLETE_RETRY_SAME_COMMAND","canonical_order":ORDER,
            "poss_tiles_total":len(pspec),"poss_tiles_complete":len(pmeta),
            "dasch_tiles_total":len(dspec),"dasch_tiles_complete":len(dmeta),
            "failures":failures,"policy_sha256":policy_sha,
            "detector_sha256":EXPECTED_DETECTOR_SHA,"method_sha256":EXPECTED_METHOD_SHA,
            "note":"Rerun exactly the same command. Valid completed tiles are skipped; failed/missing tiles are retried. No complete-pair negative conclusion is valid yet.",
        })
        print("\n"+"="*88)
        print("ORDER 61 INCOMPLETE â€” DURABLE CHECKPOINT PRESERVED")
        print("="*88)
        print(f"Failures: {len(failures)}. Rerun this same command.")
        raise SystemExit(2)

    print("\nAll required tiles complete. Aggregating candidates ...")
    p=load_rows(pmeta); d=load_rows(dmeta)
    pcsv=RESULT/"order01_poss_native_candidates.csv"
    dcsv=RESULT/"order01_dasch_native_candidates.csv"
    mcsv=RESULT/"order01_raw_coincidences.csv"
    write_csv(pcsv,p,CAND_FIELDS); write_csv(dcsv,d,CAND_FIELDS)
    matches=crossmatch(p,d,method); write_csv(mcsv,matches,MATCH_FIELDS)
    strict=[r for r in matches if r["strict_le_3arcsec"]]

    report={
        "status":"COMPLETE","run_kind":"order01_whole_footprint_native_tile_frozen_detector",
        "completed_at_utc":datetime.now(timezone.utc).isoformat(),"canonical_order":ORDER,
        "pair_key":row.get("pair_key"),"poss_exposure_id":POSS_ID,"poss_region":REGION,
        "poss_plate_id":POSS_PLATE,"dasch_plate_id":DASCH_PLATE,
        "overlap_start_utc":row.get("overlap_start_utc"),"overlap_end_utc":row.get("overlap_end_utc"),
        "actual_overlap_s":float(row["actual_overlap_s"]),"actual_overlap_minutes":float(row["actual_overlap_s"])/60,
        "detector_sha256":EXPECTED_DETECTOR_SHA,"method_sha256":EXPECTED_METHOD_SHA,"method":method_cfg,
        "policy_path":rel(POLICY),"policy_sha256":policy_sha,"poss_reference_fits":rel(REF),
        "poss_reference_fits_sha256":sha_file(REF),"poss_full_shape":[fh,fw],
        "poss_gsss_local_control_max_arcsec":gerr,"dasch_base_shape":[H,W],
        "dasch_output_shape":[outH,outW],"dasch_rotation_k":rk,"dasch_geometry_signature":gsig,
        "dasch_dense_grid_inside":True,"dasch_acquisition_bbox":[bx0,bx1,by0,by1],
        "poss_tiles_total":len(pspec),"dasch_tiles_total":len(dspec),
        "poss_candidate_count":len(p),"dasch_candidate_count_in_acquired_bbox":len(d),
        "raw_le_10arcsec":len(matches),"raw_le_3arcsec":len(strict),
        "outputs":{"poss_candidates_csv":rel(pcsv),"dasch_candidates_csv":rel(dcsv),
                   "raw_matches_csv":rel(mcsv),"failure_log_json":rel(failure_path)},
        "interpretation":"Complete deterministic native-pixel tile execution for the full order-01 POSS footprint. Raw coincidences are not transient classifications; downstream static-source, morphology, PSF, saturation, registration, controls and injection-recovery remain required.",
    }
    rp=RESULT/"order01_whole_pair_report.json"; write_json(rp,report)

    print("\n"+"="*88)
    print("ORDER 61 WHOLE-FOOTPRINT DETECTOR EXECUTION COMPLETE")
    print("="*88)
    print(f"Actual exposure overlap: {report['actual_overlap_s']:.3f} s ({report['actual_overlap_minutes']:.3f} min)")
    print("POSS accepted candidates: ",len(p))
    print("DASCH acquired candidates:",len(d))
    print("Raw <=10 arcsec matches:   ",len(matches))
    print("Raw <=3 arcsec matches:    ",len(strict))
    if matches:
        print("\nClosest raw matches (max 25):")
        for r in matches[:25]:
            print(f"  {r['separation_arcsec']:8.4f}\" | POSS {r['poss_tile_id']} SNR={r['poss_snr']:.2f} pol={r['poss_polarity']:+d} | DASCH {r['dasch_tile_id']} SNR={r['dasch_snr']:.2f} pol={r['dasch_polarity']:+d} | strict={r['strict_le_3arcsec']}")
    else:
        print("\nNo raw <=10 arcsec coincidence across the complete order-61 POSS footprint.")
    print("\nReport:",rp)
    print("POSS candidates:",pcsv)
    print("DASCH candidates:",dcsv)
    print("Raw matches:",mcsv)
    print("\nFROZEN DETECTOR WAS RUN ON THE COMPLETE ORDER-61 POSS FOOTPRINT.")
    print("No detector parameter was retuned.")


if __name__ == "__main__":
    main()

