#!/usr/bin/env python3
from pathlib import Path
import csv, hashlib, json, math, struct

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from astropy.coordinates import SkyCoord, SkyOffsetFrame
import astropy.units as u

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_final_two_registered_comparison_blinks_contract_v091.json"
)
EXPECTED_CONTRACT_SHA = "b239fe3d06f5e0a26b06988809f7ec31d71f13bf4842676362ac3fe48e910c2f"

V083_DIR = ROOT / "results" / "pair17_standardized_manual_dossiers_v083"
V083 = V083_DIR / "pair17_manual_dossier_panel_manifest_v083.csv"
V083_BANK = V083_DIR / "pair17_v083b_bank_manifest.json"
EXPECTED_V083_BANK_SHA = "6f0f749852db04fc5d1a9b8bde773a2f0dc273ee59d8e0832b72e3743e9b658b"

V085_DIR = ROOT / "results" / "pair17_unblind_blind_review_v085"
V085 = V085_DIR / "pair17_unblinded_panel_scores_v085.csv"
V085_BANK = V085_DIR / "pair17_v085_bank_manifest.json"
EXPECTED_V085_BANK_SHA = "c54982481ee6746b8e5b8b18bb9cbb2b7057b14259837f620507c4ac8c13bc71"

V079 = (
    ROOT / "results" / "pair17_pixel_followup_scan_plan_and_acquisition_v079"
    / "pair17_scan_acquisition_manifest_v079.csv"
)

CANDIDATES = ("294130","294179")
OUT = ROOT / "work" / "pair17_final_two_registered_comparison_blinks_v091"
ASSET = OUT / "assets"
MANIFEST = OUT / "pair17_final_two_registered_comparison_blinks_manifest_v091.json"

GRID_N = 640


def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def rcsv(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))


def norm(v):
    return str(v or "").strip()


def fnum(v):
    try:
        x=float(norm(v))
        return x if math.isfinite(x) else None
    except Exception:
        return None


def inum(v):
    x=fnum(v)
    return None if x is None else int(round(x))


def acquisition_map():
    out={}
    for r in rcsv(V079):
        sid=inum(r.get("scan_id"));pid=inum(r.get("physical_plate_id"))
        lp=norm(r.get("local_path"))
        if sid is not None and pid is not None and lp:
            out[(sid,pid)]=Path(lp)
    return out


def resolve_path(r,acq):
    sid=inum(r.get("scan_id"));pid=inum(r.get("physical_plate_id"))
    if sid is not None and pid is not None and (sid,pid) in acq:
        p=ROOT/acq[(sid,pid)]
        if p.is_file():
            return p.resolve()

    filename=norm(r.get("filename_scan"))
    if filename:
        matches=[]
        for base in (
            ROOT/"work"/"pair17_morphology_v076"/"scans",
            ROOT/"work"/"pair17_pixel_followup_v079"/"scans",
            ROOT/"work",
            ROOT/"results",
        ):
            if base.exists():
                matches.extend(p.resolve() for p in base.rglob(filename) if p.is_file())
        matches=sorted(set(matches))
        if len(matches)==1:
            return matches[0]
        if len(matches)>1 and sid is not None:
            hits=[p for p in matches if str(sid) in str(p.parent)]
            if len(hits)==1:
                return hits[0]
    raise RuntimeError(
        f"Cannot resolve FITS candidate={r.get('raw_match_row')} role={r.get('panel_role')}"
    )


class RawFits:
    def __init__(self,path):
        self.path=Path(path)
        self.hdul=fits.open(
            self.path,mode="readonly",memmap=True,
            do_not_scale_image_data=True,uint=False,
            ignore_missing_end=True
        )
        self.hdu=None
        for h in self.hdul:
            if int(h.header.get("NAXIS",0))>=2 and int(h.header.get("NAXIS1",0))>0 and int(h.header.get("NAXIS2",0))>0:
                self.hdu=h;break
        if self.hdu is None:
            self.hdul.close()
            raise RuntimeError(f"No 2-D image HDU: {path}")

        self.raw=self.hdu.data
        if self.raw.ndim>2:
            self.raw=self.raw.reshape((-1,)+self.raw.shape[-2:])[0]
        self.ny,self.nx=self.raw.shape[-2:]
        self.hdr=self.hdu.header
        self.bscale=float(self.hdr.get("BSCALE",1.0))
        self.bzero=float(self.hdr.get("BZERO",0.0))
        self.blank=self.hdr.get("BLANK",None)
        self.wcs=WCS(self.hdr).celestial

    def close(self):
        self.hdul.close()

    def scale(self,a):
        raw=np.asarray(a)
        out=np.asarray(raw,dtype=float)
        if self.blank is not None:
            out[raw==self.blank]=np.nan
        return out*self.bscale+self.bzero

    def sample(self,xp,yp):
        valid=(
            np.isfinite(xp)&np.isfinite(yp)&
            (xp>=0)&(yp>=0)&(xp<self.nx)&(yp<self.ny)
        )
        out=np.full(xp.shape,np.nan,dtype=float)
        if not np.any(valid):
            return out
        xi=np.rint(xp[valid]).astype(int)
        yi=np.rint(yp[valid]).astype(int)
        xmin,xmax=int(xi.min()),int(xi.max())
        ymin,ymax=int(yi.min()),int(yi.max())
        block=self.scale(self.raw[ymin:ymax+1,xmin:xmax+1])
        out[valid]=block[yi-ymin,xi-xmin]
        return out


def local_scale(w):
    s=np.asarray(proj_plane_pixel_scales(w),dtype=float)*3600.0
    s=s[np.isfinite(s)&(s>0)]
    if s.size==0:
        raise RuntimeError("Cannot derive WCS pixel scale")
    return float(np.max(s))


def robust_limits(a):
    v=np.asarray(a,dtype=float)
    v=v[np.isfinite(v)]
    if v.size==0:
        return 0.0,1.0
    lo,hi=np.percentile(v,[0.5,99.5])
    if not np.isfinite(lo) or not np.isfinite(hi) or lo==hi:
        lo,hi=float(np.nanmin(v)),float(np.nanmax(v))
    if lo==hi:
        hi=lo+1
    return float(lo),float(hi)


def to_rgb(a):
    lo,hi=robust_limits(a)
    g=np.zeros(np.asarray(a).shape,dtype=np.uint8)
    finite=np.isfinite(a)
    if np.any(finite):
        x=(np.asarray(a,dtype=float)[finite]-lo)/(hi-lo)
        x=np.clip(x,0,1)
        g[finite]=np.rint(x*255).astype(np.uint8)
    return np.repeat(g[:,:,None],3,axis=2)


def write_bmp(rgb,path):
    rgb=np.asarray(rgb,dtype=np.uint8)
    h,w,_=rgb.shape
    row_bytes=w*3
    pad=(4-row_bytes%4)%4
    pixels=(row_bytes+pad)*h
    with Path(path).open("wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<IHHI",54+pixels,0,0,54))
        f.write(struct.pack("<IIIHHIIIIII",40,w,h,1,24,0,pixels,2835,2835,0,0))
        padb=bytes([0])*pad
        # array row 0 is lower sky display row; BMP writes bottom-up
        for row in rgb:
            f.write(row[:,::-1].tobytes())
            if pad:
                f.write(padb)


def target_world(img,row):
    x=fnum(row.get("target_pixel_x"));y=fnum(row.get("target_pixel_y"))
    if x is None or y is None:
        raise RuntimeError("Missing v083 target pixel")
    c=img.wcs.pixel_to_world(x,y)
    return SkyCoord(c.ra,c.dec,frame="icrs")


def common_grid(center,scale,n=GRID_N):
    ax=(np.arange(n)-(n-1)/2.0)*scale
    xx,yy=np.meshgrid(ax,ax)
    off=SkyCoord(
        lon=xx*u.arcsec,lat=yy*u.arcsec,
        frame=SkyOffsetFrame(origin=center)
    )
    return off.transform_to("icrs")


def score_map():
    out={}
    for r in rcsv(V085):
        key=(
            norm(r.get("raw_match_row")),
            norm(r.get("panel_role")),
            norm(r.get("physical_plate_id")),
            norm(r.get("scan_id")),
        )
        out[key]=r
    return out


def main():
    print("="*120)
    print("PAIR 17 — FINAL TWO REGISTERED COMPARISON BLINKS v091")
    print("="*120)
    print("Candidates:",", ".join(CANDIDATES))
    print("Display-only")
    print("Network calls: 0")
    print("Detector reruns: 0")
    print("New source measurements: 0")
    print("Disposition changes: NONE")
    print()

    if sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v091 contract SHA mismatch")
    if sha(V083_BANK)!=EXPECTED_V083_BANK_SHA:
        raise RuntimeError("v083b bank SHA mismatch")
    if sha(V085_BANK)!=EXPECTED_V085_BANK_SHA:
        raise RuntimeError("v085 bank SHA mismatch")

    rows=rcsv(V083)
    acq=acquisition_map()
    scores=score_map()

    science={}
    comparisons=[]
    for r in rows:
        cid=norm(r.get("raw_match_row"))
        if cid not in CANDIDATES:
            continue
        role=norm(r.get("panel_role"))
        obs=norm(r.get("observatory")).upper()
        if role=="SCIENCE_HAMBURG":
            science[(cid,"HAMBURG")]=r
        elif role=="SCIENCE_BAMBERG":
            science[(cid,"BAMBERG")]=r
        elif "QUALIFIED_NEGATIVE" in role:
            comparisons.append(r)

    comparisons.sort(key=lambda r:(
        int(norm(r["raw_match_row"])),
        norm(r.get("observatory")),
        abs(fnum(r.get("gap_hours")) or 1e99),
        norm(r.get("panel_role"))
    ))

    if not comparisons:
        raise RuntimeError("No qualified-negative comparison panels found")

    ASSET.mkdir(parents=True,exist_ok=True)
    records=[]

    for i,comp in enumerate(comparisons,1):
        cid=norm(comp["raw_match_row"])
        obs=norm(comp.get("observatory")).upper()
        scirow=science.get((cid,obs))
        if scirow is None:
            raise RuntimeError(f"{cid} {obs}: matching science panel missing")

        sp=resolve_path(scirow,acq)
        cp=resolve_path(comp,acq)

        print(
            f"[{i:02d}/{len(comparisons):02d}] {cid} {obs} "
            f"{comp['panel_role']} gap={comp.get('gap_hours')} h"
        )

        si=RawFits(sp); ci=RawFits(cp)
        try:
            sw=target_world(si,scirow)
            cw=target_world(ci,comp)

            scale=max(local_scale(si.wcs),local_scale(ci.wcs))

            sg=common_grid(sw,scale)
            cg=common_grid(cw,scale)

            sx,sy=si.wcs.world_to_pixel(sg)
            cx,cy=ci.wcs.world_to_pixel(cg)

            sa=si.sample(np.asarray(sx),np.asarray(sy))
            ca=ci.sample(np.asarray(cx),np.asarray(cy))

            safe=f"{cid}_{obs}_{i:02d}"
            sf=ASSET/f"{safe}_science.bmp"
            cf=ASSET/f"{safe}_comparison.bmp"
            write_bmp(to_rgb(sa),sf)
            write_bmp(to_rgb(ca),cf)

            skey=(
                cid,norm(comp.get("panel_role")),
                norm(comp.get("physical_plate_id")),
                norm(comp.get("scan_id"))
            )
            sc=scores.get(skey,{})

            records.append({
                "raw_match_row":cid,
                "observatory":obs,
                "comparison_role":norm(comp.get("panel_role")),
                "gap_hours":fnum(comp.get("gap_hours")),
                "relation":norm(comp.get("relation_to_common_overlap")),
                "comparison_blind_code":norm(sc.get("blind_code")),
                "comparison_manual_feature":norm(sc.get("feature_at_crosshair")),
                "comparison_manual_morphology":norm(sc.get("morphology")),
                "comparison_manual_confidence":norm(sc.get("confidence_1_to_5")),
                "comparison_manual_notes":norm(sc.get("notes")),
                "science_plate":norm(scirow.get("physical_plate_id")),
                "comparison_plate":norm(comp.get("physical_plate_id")),
                "science_fits":str(sp),
                "comparison_fits":str(cp),
                "science_fits_sha256":sha(sp),
                "comparison_fits_sha256":sha(cp),
                "display_scale_arcsec_per_px":scale,
                "science_target_world_ra_deg":float(sw.ra.deg),
                "science_target_world_dec_deg":float(sw.dec.deg),
                "comparison_target_world_ra_deg":float(cw.ra.deg),
                "comparison_target_world_dec_deg":float(cw.dec.deg),
                "assets":{"science":sf.name,"comparison":cf.name}
            })
        finally:
            si.close();ci.close()

    MANIFEST.write_text(
        json.dumps({
            "status":"COMPLETE",
            "analysis_kind":"pair17_final_two_registered_comparison_blinks_v091",
            "contract_sha256":EXPECTED_CONTRACT_SHA,
            "candidates":list(CANDIDATES),
            "pairs":len(records),
            "records":records,
            "display_only":True,
            "candidate_dispositions_changed":False
        },indent=2,sort_keys=True)+"\n",
        encoding="utf-8"
    )

    style="""
    body{font-family:system-ui,sans-serif;background:#101010;color:#eee;margin:24px}
    .intro{max-width:1200px;color:#ccc;line-height:1.45}
    .card{border:1px solid #444;border-radius:10px;padding:16px;margin:22px 0;background:#181818}
    .meta{font-family:ui-monospace,monospace;font-size:12px;color:#bbb;white-space:pre-wrap}
    .stack{position:relative;width:min(760px,90vw);aspect-ratio:1/1;background:#000;border:1px solid #444}
    .stack img{position:absolute;left:0;top:0;width:100%;height:100%;image-rendering:pixelated}
    .cmp{opacity:0}
    .cross:before,.cross:after{content:"";position:absolute;background:#ff2d55;z-index:5;pointer-events:none}
    .cross:before{left:50%;top:0;width:1px;height:100%}
    .cross:after{top:50%;left:0;height:1px;width:100%}
    .controls{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin:10px 0}
    input[type=range]{width:260px}
    button{padding:7px 11px}
    """

    js=r"""
    function setup(id){
      const cmp=document.getElementById(id+"_cmp");
      const slider=document.getElementById(id+"_slider");
      const stack=document.getElementById(id+"_stack");
      let timer=null,state=0;
      function op(v){cmp.style.opacity=v;slider.value=Math.round(v*100);}
      document.getElementById(id+"_sci").onclick=()=>op(0);
      document.getElementById(id+"_comparison").onclick=()=>op(1);
      slider.oninput=()=>op(parseInt(slider.value)/100);
      document.getElementById(id+"_cross").onclick=()=>stack.classList.toggle("cross");
      document.getElementById(id+"_blink").onclick=(e)=>{
        if(timer){clearInterval(timer);timer=null;e.target.textContent="Start blink";return;}
        e.target.textContent="Stop blink";
        timer=setInterval(()=>{state=1-state;op(state);},650);
      };
    }
    """

    h=[
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Pair 17 final-two registered comparison blinks v091</title>",
        f"<style>{style}</style></head><body>",
        "<h1>Pair 17 — 294130 / 294179 registered comparison blinks v091</h1>",
        "<p class='intro'>Each card compares a science plate to one frozen qualified-negative panel "
        "from the same observatory. Both images are centred on their own banked v083b target pixel and "
        "placed on matching local sky-offset grids. Nearest-neighbour resampling only; independent "
        "0.5–99.5 percentile stretches; no subtraction, filtering, detection, or new measurement.</p>"
    ]

    for i,r in enumerate(records,1):
        ident=f"p{i}"
        meta=(
            f"Candidate: {r['raw_match_row']}    Observatory: {r['observatory']}\n"
            f"Comparison: {r['comparison_role']}    gap_hours={r['gap_hours']}\n"
            f"Blind comparison: {r['comparison_blind_code']} — "
            f"{r['comparison_manual_feature']} / {r['comparison_manual_morphology']} "
            f"/ confidence {r['comparison_manual_confidence']}\n"
            f"Notes: {r['comparison_manual_notes']}\n"
            f"Science plate: {r['science_plate']}    Comparison plate: {r['comparison_plate']}\n"
            f"Display scale: {r['display_scale_arcsec_per_px']:.6f} arcsec/px"
        )
        h += [
            "<div class='card'>",
            f"<h2>{r['raw_match_row']} — {r['observatory']} — {r['comparison_role']}</h2>",
            f"<div class='meta'>{meta}</div>",
            "<div class='controls'>",
            f"<button id='{ident}_sci'>Science</button>",
            f"<button id='{ident}_comparison'>Comparison</button>",
            f"<button id='{ident}_blink'>Start blink</button>",
            f"<button id='{ident}_cross'>Toggle crosshair</button>",
            f"<label>Opacity <input id='{ident}_slider' type='range' min='0' max='100' value='0'></label>",
            "</div>",
            f"<div class='stack' id='{ident}_stack'>",
            f"<img src='assets/{r['assets']['science']}'>",
            f"<img id='{ident}_cmp' class='cmp' src='assets/{r['assets']['comparison']}'>",
            "</div></div>",
            f"<script>{js}</script><script>setup('{ident}');</script>"
        ]

    h.append("</body></html>")
    index=OUT/"index.html"
    index.write_text("\n".join(h),encoding="utf-8")

    print()
    print("="*120)
    print("v091 FINAL-TWO REGISTERED COMPARISON BLINKS COMPLETE")
    print("="*120)
    print("Blink pairs:",len(records))
    print(index)
    print("STAGE STATUS: COMPLETE")


if __name__=="__main__":
    main()
