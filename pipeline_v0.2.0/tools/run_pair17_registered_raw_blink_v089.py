#!/usr/bin/env python3
from pathlib import Path
import csv, hashlib, json, math, os, struct

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from astropy.coordinates import SkyCoord, SkyOffsetFrame
import astropy.units as u

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_registered_raw_blink_contract_v089.json"
)
EXPECTED_CONTRACT_SHA = "71ec560a0799440e9672e498e86c4a0e18c2fd97773d55a46bb9c368880a6492"

V075 = (
    ROOT / "results" / "pair17_epoch_aware_gaia_static_triage_v075"
    / "pair17_epoch_aware_gaia_static_triage_v075.csv"
)
EXPECTED_V075_SHA = "cc571a4da103dc3900907fe9568567dd540f8f85217b7e7e73ca4442239f2097"

V087_BANK = (
    ROOT / "results" / "pair17_direct_detector_pixel_provenance_v087"
    / "pair17_v087_bank_manifest.json"
)
EXPECTED_V087_BANK_SHA = "f71c234c35c6c8c679ec259d6401cd37eb556e2a5309fd2c290debb6a2caf6ae"

V088_BANK = (
    ROOT / "results" / "pair17_detector_semantics_provenance_audit_v088"
    / "pair17_v088a_bank_manifest.json"
)
EXPECTED_V088_BANK_SHA = "6f27acdf19c16a866af8c593f93be2fab5505fb04de99ad108529ae28895412f"

V083 = (
    ROOT / "results" / "pair17_standardized_manual_dossiers_v083"
    / "pair17_manual_dossier_panel_manifest_v083.csv"
)

V079 = (
    ROOT / "results" / "pair17_pixel_followup_scan_plan_and_acquisition_v079"
    / "pair17_scan_acquisition_manifest_v079.csv"
)

CANDIDATES = ("293118", "293841")
OUT = ROOT / "work" / "pair17_registered_raw_blink_v089"
ASSET = OUT / "assets"
MANIFEST = OUT / "pair17_registered_raw_blink_manifest_v089.json"

GRID_N = 640
RAW_HALF = 512


def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(8*1024*1024), b""):
            h.update(b)
    return h.hexdigest()


def rcsv(p):
    with Path(p).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def norm(v):
    return str(v or "").strip()


def fnum(v):
    try:
        x = float(norm(v))
        return x if math.isfinite(x) else None
    except Exception:
        return None


def inum(v):
    x = fnum(v)
    return None if x is None else int(round(x))


def unique_file(basename):
    matches = []
    for base in (
        ROOT / "work" / "pair17_morphology_v076" / "scans",
        ROOT / "work" / "pair17_pixel_followup_v079" / "scans",
        ROOT / "work",
        ROOT / "results",
    ):
        if base.exists():
            matches.extend(p.resolve() for p in base.rglob(basename) if p.is_file())
    matches = sorted(set(matches))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one local {basename}; found {len(matches)}: {matches}"
        )
    return matches[0]


class RawFitsImage:
    """
    Memory-efficient FITS image accessor.

    Astropy is asked not to scale image data so large scans remain memory-mapped.
    BZERO/BSCALE/BLANK are applied only to the small slices used for display.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.hdul = fits.open(
            self.path,
            mode="readonly",
            memmap=True,
            do_not_scale_image_data=True,
            uint=False,
            ignore_missing_end=True,
        )
        self.hdu_index = None
        self.hdu = None
        for i, h in enumerate(self.hdul):
            hdr = h.header
            if int(hdr.get("NAXIS",0)) >= 2 and int(hdr.get("NAXIS1",0)) > 0 and int(hdr.get("NAXIS2",0)) > 0:
                self.hdu_index = i
                self.hdu = h
                break
        if self.hdu is None:
            self.hdul.close()
            raise RuntimeError(f"No image HDU in {path}")

        self.header = self.hdu.header
        self.raw = self.hdu.data
        if self.raw.ndim > 2:
            self.raw = self.raw.reshape((-1,) + self.raw.shape[-2:])[0]
        self.ny, self.nx = self.raw.shape[-2], self.raw.shape[-1]
        self.bscale = float(self.header.get("BSCALE", 1.0))
        self.bzero = float(self.header.get("BZERO", 0.0))
        self.blank = self.header.get("BLANK", None)
        self.wcs = WCS(self.header).celestial

    def close(self):
        self.hdul.close()

    def _scale(self, arr):
        a = np.asarray(arr, dtype=float)
        if self.blank is not None:
            a[np.asarray(arr) == self.blank] = np.nan
        a = a * self.bscale + self.bzero
        return a

    def slice(self, x0, x1, y0, y1):
        x0 = max(0, int(x0)); x1 = min(self.nx, int(x1))
        y0 = max(0, int(y0)); y1 = min(self.ny, int(y1))
        return self._scale(self.raw[y0:y1, x0:x1]), x0, y0

    def registered_sample(self, xp, yp):
        valid = (
            np.isfinite(xp) & np.isfinite(yp)
            & (xp >= 0) & (yp >= 0)
            & (xp < self.nx) & (yp < self.ny)
        )
        out = np.full(xp.shape, np.nan, dtype=float)
        if not np.any(valid):
            return out

        xi = np.rint(xp[valid]).astype(int)
        yi = np.rint(yp[valid]).astype(int)

        xmin, xmax = int(xi.min()), int(xi.max())
        ymin, ymax = int(yi.min()), int(yi.max())
        block, bx0, by0 = self.slice(xmin, xmax+1, ymin, ymax+1)

        out[valid] = block[yi-by0, xi-bx0]
        return out


def robust_limits(a):
    v = np.asarray(a, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(v, [0.5,99.5])
    if not np.isfinite(lo) or not np.isfinite(hi) or lo == hi:
        lo, hi = float(np.nanmin(v)), float(np.nanmax(v))
    if lo == hi:
        hi = lo + 1.0
    return float(lo), float(hi)


def to_rgb(a):
    lo, hi = robust_limits(a)
    g = np.zeros(np.asarray(a).shape, dtype=np.uint8)
    finite = np.isfinite(a)
    if np.any(finite):
        x = (np.asarray(a,dtype=float)[finite]-lo)/(hi-lo)
        x = np.clip(x,0,1)
        g[finite] = np.rint(x*255).astype(np.uint8)
    return np.repeat(g[:,:,None],3,axis=2)


def write_bmp(rgb, path):
    rgb = np.asarray(rgb,dtype=np.uint8)
    h,w,c = rgb.shape
    if c != 3:
        raise RuntimeError("RGB expected")
    row_bytes = w*3
    pad = (4-(row_bytes%4))%4
    pixel_bytes=(row_bytes+pad)*h
    size=14+40+pixel_bytes
    with Path(path).open("wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<IHHI", size,0,0,54))
        f.write(struct.pack("<IIIHHIIIIII",40,w,h,1,24,0,pixel_bytes,2835,2835,0,0))
        padb=bytes([0])*pad
        for row in rgb[::-1]:
            f.write(row[:,::-1].tobytes())
            if pad:
                f.write(padb)


def local_scale_arcsec(w):
    scales = np.asarray(proj_plane_pixel_scales(w), dtype=float)*3600.0
    scales = scales[np.isfinite(scales) & (scales>0)]
    if scales.size == 0:
        raise RuntimeError("Could not derive local WCS pixel scale")
    return float(np.max(scales))


def raw_crop(img, center):
    x,y = img.wcs.world_to_pixel(center)
    x=float(x); y=float(y)
    arr,x0,y0 = img.slice(
        int(round(x))-RAW_HALF,
        int(round(x))+RAW_HALF,
        int(round(y))-RAW_HALF,
        int(round(y))+RAW_HALF
    )
    return arr, x, y, x0, y0


def common_sky_grid(center, scale_arcsec, n=GRID_N):
    # Use a local sky-offset frame. Pixel centers are symmetric around zero.
    ax = (np.arange(n) - (n-1)/2.0) * scale_arcsec
    xx,yy = np.meshgrid(ax, ax)
    frame = SkyOffsetFrame(origin=center)
    off = SkyCoord(
        lon=xx*u.arcsec,
        lat=yy*u.arcsec,
        frame=frame
    )
    world = off.transform_to("icrs")
    return world


def main():
    print("="*120)
    print("PAIR 17 — REGISTERED RAW BLINK DIAGNOSTIC v089")
    print("="*120)
    print("Display-only; nearest-neighbour sky registration")
    print("Network calls: 0")
    print("Detector reruns: 0")
    print("New source measurements: 0")
    print("Candidate disposition changes: NONE")
    print()

    if not CONTRACT.is_file() or sha(CONTRACT) != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v089 contract SHA mismatch")
    if sha(V075) != EXPECTED_V075_SHA:
        raise RuntimeError("v075 SHA mismatch")
    if sha(V087_BANK) != EXPECTED_V087_BANK_SHA:
        raise RuntimeError("v087 bank SHA mismatch")
    if sha(V088_BANK) != EXPECTED_V088_BANK_SHA:
        raise RuntimeError("v088a bank SHA mismatch")

    v075 = {norm(r["raw_match_row"]):r for r in rcsv(V075)}
    v083 = rcsv(V083)

    # Exact local scan files already used in the prior viewer.
    science_path = unique_file("LA08164_y.fits")
    close_path = unique_file("LA08167_x.fits")

    OUT.mkdir(parents=True, exist_ok=True)
    ASSET.mkdir(parents=True, exist_ok=True)

    sci = RawFitsImage(science_path)
    close = RawFitsImage(close_path)

    records=[]
    try:
        sci_scale=local_scale_arcsec(sci.wcs)
        close_scale=local_scale_arcsec(close.wcs)

        for cid in CANDIDATES:
            r=v075[cid]
            ra=fnum(r.get("a_ra_deg"))
            dec=fnum(r.get("a_dec_deg"))
            if ra is None or dec is None:
                raise RuntimeError(f"{cid}: missing frozen Hamburg RA/Dec")

            center=SkyCoord(ra*u.deg,dec*u.deg,frame="icrs")

            # Use the coarser native plate scale. This avoids creating apparent
            # detail not present in either source image.
            scale=max(sci_scale,close_scale)
            world=common_sky_grid(center,scale)

            sx,sy=sci.wcs.world_to_pixel(world)
            cx,cy=close.wcs.world_to_pixel(world)

            sreg=sci.registered_sample(np.asarray(sx),np.asarray(sy))
            creg=close.registered_sample(np.asarray(cx),np.asarray(cy))

            sraw,sx0,sy0,srx0,sry0=raw_crop(sci,center)
            craw,cx0,cy0,crx0,cry0=raw_crop(close,center)

            files={}
            for key,arr in (
                ("science_registered",sreg),
                ("close_registered",creg),
                ("science_raw",sraw),
                ("close_raw",craw),
            ):
                p=ASSET/f"{cid}_{key}.bmp"
                write_bmp(to_rgb(arr),p)
                files[key]=p.name

            records.append({
                "raw_match_row":cid,
                "center_ra_deg":ra,
                "center_dec_deg":dec,
                "display_scale_arcsec_per_px":scale,
                "science_native_scale_arcsec_per_px":sci_scale,
                "close_native_scale_arcsec_per_px":close_scale,
                "science_center_pixel_x":sx0,
                "science_center_pixel_y":sy0,
                "close_center_pixel_x":cx0,
                "close_center_pixel_y":cy0,
                "science_path":str(science_path),
                "close_path":str(close_path),
                "science_path_sha256":sha(science_path),
                "close_path_sha256":sha(close_path),
                "assets":files
            })
    finally:
        sci.close()
        close.close()

    MANIFEST.write_text(
        json.dumps({
            "status":"COMPLETE",
            "analysis_kind":"pair17_registered_raw_blink_diagnostic_v089",
            "contract_sha256":EXPECTED_CONTRACT_SHA,
            "candidates":records,
            "display_only":True,
            "nearest_neighbour_registration":True,
            "candidate_dispositions_changed":False
        },indent=2,sort_keys=True)+"\n",
        encoding="utf-8"
    )

    # Interactive HTML: registered images are stacked exactly.
    style = """
    body{font-family:system-ui,sans-serif;background:#101010;color:#eee;margin:24px}
    .note{max-width:1200px;color:#ccc;line-height:1.45}
    .candidate{border:1px solid #444;border-radius:12px;padding:18px;margin:28px 0;background:#181818}
    .meta{font-family:ui-monospace,monospace;font-size:13px;color:#bbb;white-space:pre-wrap}
    .row{display:grid;grid-template-columns:minmax(500px,720px) minmax(420px,1fr);gap:18px;align-items:start}
    .stack{position:relative;width:100%;aspect-ratio:1/1;background:#000;overflow:hidden;border:1px solid #444}
    .stack img{position:absolute;left:0;top:0;width:100%;height:100%;image-rendering:pixelated}
    .later{opacity:0}
    .cross:before,.cross:after{content:"";position:absolute;background:#ff2d55;z-index:5;pointer-events:none}
    .cross:before{left:50%;top:0;width:1px;height:100%}
    .cross:after{top:50%;left:0;height:1px;width:100%}
    .controls{margin:10px 0 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
    button{padding:7px 12px}
    input[type=range]{width:260px}
    .rawgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
    .rawgrid img{width:100%;height:auto;border:1px solid #333}
    .label{font-size:12px;color:#aaa;margin:4px 0}
    """

    js = r"""
    function setup(id){
      const later=document.getElementById(id+"_later");
      const slider=document.getElementById(id+"_slider");
      const stack=document.getElementById(id+"_stack");
      let timer=null, state=0;
      function setOpacity(v){later.style.opacity=v; slider.value=Math.round(v*100);}
      document.getElementById(id+"_science").onclick=()=>setOpacity(0);
      document.getElementById(id+"_laterbtn").onclick=()=>setOpacity(1);
      slider.oninput=()=>setOpacity(parseInt(slider.value)/100);
      document.getElementById(id+"_mark").onclick=()=>stack.classList.toggle("cross");
      document.getElementById(id+"_blink").onclick=(e)=>{
        if(timer){clearInterval(timer);timer=null;e.target.textContent="Start blink";return;}
        e.target.textContent="Stop blink";
        timer=setInterval(()=>{state=1-state;setOpacity(state);},650);
      };
    }
    """

    html=[
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Pair 17 registered raw blink v089</title>",
        f"<style>{style}</style></head><body>",
        "<h1>Pair 17 — registered raw-image blink v089</h1>",
        "<p class='note'>Candidates 293118 and 293841. Left: Hamburg science plate and Hamburg +1.03 h plate "
        "registered onto the same sky grid with nearest-neighbour sampling only. The displayed scale is the coarser "
        "of the two native WCS scales. Right: independent raw native-pixel crops around the same frozen sky coordinate. "
        "Each image has its own 0.5–99.5 percentile display stretch. No subtraction, smoothing, high-pass filter, "
        "source detection, or candidate-state change is performed.</p>"
    ]

    for rec in records:
        cid=rec["raw_match_row"]
        meta=(
            f"Frozen centre: RA {rec['center_ra_deg']:.9f}°, Dec {rec['center_dec_deg']:.9f}°\n"
            f"Registered display scale: {rec['display_scale_arcsec_per_px']:.6f} arcsec/px\n"
            f"Science native scale: {rec['science_native_scale_arcsec_per_px']:.6f} arcsec/px\n"
            f"Later native scale: {rec['close_native_scale_arcsec_per_px']:.6f} arcsec/px\n"
            f"Science centre pixel: ({rec['science_center_pixel_x']:.3f}, {rec['science_center_pixel_y']:.3f})\n"
            f"Later centre pixel: ({rec['close_center_pixel_x']:.3f}, {rec['close_center_pixel_y']:.3f})"
        )
        a=rec["assets"]
        html += [
            f"<div class='candidate'><h2>Candidate {cid}</h2>",
            f"<div class='meta'>{meta}</div>",
            "<div class='row'><div>",
            "<div class='controls'>",
            f"<button id='{cid}_science'>Science</button>",
            f"<button id='{cid}_laterbtn'>+1.03 h</button>",
            f"<button id='{cid}_blink'>Start blink</button>",
            f"<button id='{cid}_mark'>Toggle crosshair</button>",
            f"<label>Opacity <input id='{cid}_slider' type='range' min='0' max='100' value='0'></label>",
            "</div>",
            f"<div class='stack' id='{cid}_stack'>",
            f"<img src='assets/{a['science_registered']}' alt='science registered'>",
            f"<img class='later' id='{cid}_later' src='assets/{a['close_registered']}' alt='later registered'>",
            "</div></div>",
            "<div><div class='rawgrid'>",
            f"<div><div class='label'>Science plate — raw native-pixel crop</div><img src='assets/{a['science_raw']}'></div>",
            f"<div><div class='label'>+1.03 h plate — raw native-pixel crop</div><img src='assets/{a['close_raw']}'></div>",
            "</div></div></div></div>"
        ]

    html += [f"<script>{js}</script>"]
    for cid in CANDIDATES:
        html.append(f"<script>setup('{cid}');</script>")
    html.append("</body></html>")

    index=OUT/"index.html"
    index.write_text("\n".join(html),encoding="utf-8")

    print()
    print("="*120)
    print("v089 REGISTERED RAW BLINK VIEWER COMPLETE")
    print("="*120)
    print(index)
    print("STAGE STATUS: COMPLETE")


if __name__ == "__main__":
    main()
