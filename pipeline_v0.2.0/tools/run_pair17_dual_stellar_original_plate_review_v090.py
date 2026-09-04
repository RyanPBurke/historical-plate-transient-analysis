#!/usr/bin/env python3
from pathlib import Path
import csv, hashlib, json, math, os, struct

import numpy as np
from astropy.io import fits

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = (
    ROOT / "research" / "prospective_freezes"
    / "pair17_dual_stellar_original_plate_review_contract_v090.json"
)
EXPECTED_CONTRACT_SHA = "099b06b0c03010d255c45a12337f6275859b49ddda562ca94e99d29b435e2fc0"

V083_DIR = ROOT / "results" / "pair17_standardized_manual_dossiers_v083"
V083 = V083_DIR / "pair17_manual_dossier_panel_manifest_v083.csv"
V083_BANK = V083_DIR / "pair17_v083b_bank_manifest.json"
EXPECTED_V083_BANK_SHA = "6f0f749852db04fc5d1a9b8bde773a2f0dc273ee59d8e0832b72e3743e9b658b"

V085_DIR = ROOT / "results" / "pair17_unblind_blind_review_v085"
V085 = V085_DIR / "pair17_unblinded_panel_scores_v085.csv"
V085_BANK = V085_DIR / "pair17_v085_bank_manifest.json"
EXPECTED_V085_BANK_SHA = "c54982481ee6746b8e5b8b18bb9cbb2b7057b14259837f620507c4ac8c13bc71"

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

V079 = (
    ROOT / "results" / "pair17_pixel_followup_scan_plan_and_acquisition_v079"
    / "pair17_scan_acquisition_manifest_v079.csv"
)

CANDIDATES = ("293470","294052","294130","294179")
OUT = ROOT / "work" / "pair17_dual_stellar_original_plate_review_v090"
ASSET = OUT / "assets"
MANIFEST = OUT / "pair17_dual_stellar_original_plate_review_manifest_v090.json"

REGION_HALF = 1024
ZOOM_HALF = 256


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


def robust_limits(a):
    v=np.asarray(a,dtype=float)
    v=v[np.isfinite(v)]
    if v.size==0:
        return 0.0,1.0
    lo,hi=np.percentile(v,[0.5,99.5])
    if not np.isfinite(lo) or not np.isfinite(hi) or lo==hi:
        lo,hi=float(np.nanmin(v)),float(np.nanmax(v))
    if lo==hi:
        hi=lo+1.0
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


def draw_marker(rgb,x,y,box_half=None):
    # rgb rows are FITS-array rows; writer below preserves row0 as display bottom.
    h,w,_=rgb.shape
    xi=int(round(x)); yi=int(round(y))
    if 0 <= xi < w:
        rgb[:,max(0,xi-1):min(w,xi+2),:]=255
    if 0 <= yi < h:
        rgb[max(0,yi-1):min(h,yi+2),:,:]=255
    if box_half is not None:
        x0=max(0,xi-int(box_half)); x1=min(w-1,xi+int(box_half))
        y0=max(0,yi-int(box_half)); y1=min(h-1,yi+int(box_half))
        rgb[y0:min(h,y0+2),x0:x1+1,:]=255
        rgb[max(0,y1-1):y1+1,x0:x1+1,:]=255
        rgb[y0:y1+1,x0:min(w,x0+2),:]=255
        rgb[y0:y1+1,max(0,x1-1):x1+1,:]=255


def write_bmp(rgb,path):
    rgb=np.asarray(rgb,dtype=np.uint8)
    h,w,c=rgb.shape
    row_bytes=w*3
    pad=(4-(row_bytes%4))%4
    pixel_bytes=(row_bytes+pad)*h
    size=54+pixel_bytes
    with Path(path).open("wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<IHHI",size,0,0,54))
        f.write(struct.pack("<IIIHHIIIIII",40,w,h,1,24,0,pixel_bytes,2835,2835,0,0))
        padb=bytes([0])*pad
        # FITS array row 0 corresponds to the lower display row, matching BMP bottom-up order.
        for row in rgb:
            f.write(row[:,::-1].tobytes())
            if pad:
                f.write(padb)


class RawFits:
    def __init__(self,path):
        self.path=Path(path)
        self.hdul=fits.open(
            self.path,mode="readonly",memmap=True,
            do_not_scale_image_data=True,uint=False,
            ignore_missing_end=True
        )
        self.hdu_index=None
        self.hdu=None
        for i,h in enumerate(self.hdul):
            if int(h.header.get("NAXIS",0))>=2 and int(h.header.get("NAXIS1",0))>0 and int(h.header.get("NAXIS2",0))>0:
                self.hdu_index=i;self.hdu=h;break
        if self.hdu is None:
            self.hdul.close()
            raise RuntimeError(f"No 2D image HDU: {path}")
        self.raw=self.hdu.data
        if self.raw.ndim>2:
            self.raw=self.raw.reshape((-1,)+self.raw.shape[-2:])[0]
        self.ny,self.nx=self.raw.shape[-2:]
        self.bscale=float(self.hdu.header.get("BSCALE",1.0))
        self.bzero=float(self.hdu.header.get("BZERO",0.0))
        self.blank=self.hdu.header.get("BLANK",None)

    def scale(self,a):
        raw=np.asarray(a)
        out=np.asarray(raw,dtype=float)
        if self.blank is not None:
            out[raw==self.blank]=np.nan
        return out*self.bscale+self.bzero

    def crop(self,cx,cy,half):
        x0=max(0,int(round(cx))-half)
        x1=min(self.nx,int(round(cx))+half)
        y0=max(0,int(round(cy))-half)
        y1=min(self.ny,int(round(cy))+half)
        return self.scale(self.raw[y0:y1,x0:x1]),x0,y0

    def overview(self,max_dim=1400):
        step=max(1,int(math.ceil(max(self.nx,self.ny)/max_dim)))
        return self.scale(self.raw[::step,::step]),step

    def close(self):
        self.hdul.close()


def acquisition_map():
    out={}
    for r in rcsv(V079):
        sid=inum(r.get("scan_id")); pid=inum(r.get("physical_plate_id"))
        lp=norm(r.get("local_path"))
        if sid is not None and pid is not None and lp:
            out[(sid,pid)]=Path(lp)
    return out


def resolve_path(r,acq):
    sid=inum(r.get("scan_id")); pid=inum(r.get("physical_plate_id"))
    if sid is not None and pid is not None:
        lp=acq.get((sid,pid))
        if lp is not None:
            p=ROOT/lp
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
        f"Cannot resolve FITS: candidate={r.get('raw_match_row')} role={r.get('panel_role')} "
        f"plate={pid} scan={sid} filename={filename!r}"
    )


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
    print("PAIR 17 — DUAL-STELLAR ORIGINAL PLATE REVIEW v090")
    print("="*120)
    print("Candidates:",", ".join(CANDIDATES))
    print("Display-only; all already-selected v083b panels")
    print("Network calls: 0")
    print("Detector reruns: 0")
    print("New feature measurements: 0")
    print("Disposition changes: NONE")
    print()

    if sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v090 contract SHA mismatch")
    if sha(V083_BANK)!=EXPECTED_V083_BANK_SHA:
        raise RuntimeError("v083b bank SHA mismatch")
    if sha(V085_BANK)!=EXPECTED_V085_BANK_SHA:
        raise RuntimeError("v085 bank SHA mismatch")
    if sha(V087_BANK)!=EXPECTED_V087_BANK_SHA:
        raise RuntimeError("v087 bank SHA mismatch")
    if sha(V088_BANK)!=EXPECTED_V088_BANK_SHA:
        raise RuntimeError("v088a bank SHA mismatch")

    ASSET.mkdir(parents=True,exist_ok=True)
    acq=acquisition_map()
    scores=score_map()

    rows=[
        r for r in rcsv(V083)
        if norm(r.get("raw_match_row")) in CANDIDATES
    ]
    if not rows:
        raise RuntimeError("No v083 panels found for v090 candidates")

    rows.sort(key=lambda r:(
        int(norm(r["raw_match_row"])),
        0 if "SCIENCE_HAMBURG" in norm(r.get("panel_role")) else
        1 if "SCIENCE_BAMBERG" in norm(r.get("panel_role")) else 2,
        norm(r.get("panel_role")),
        inum(r.get("physical_plate_id")) or -1
    ))

    records=[]
    for i,r in enumerate(rows,1):
        cid=norm(r["raw_match_row"])
        role=norm(r.get("panel_role"))
        pid=norm(r.get("physical_plate_id"))
        sid=norm(r.get("scan_id"))
        cx=fnum(r.get("target_pixel_x")); cy=fnum(r.get("target_pixel_y"))
        if cx is None or cy is None:
            raise RuntimeError(f"{cid} {role}: target pixel missing")

        p=resolve_path(r,acq)
        print(f"[{i:02d}/{len(rows):02d}] {cid} {role} -> {p.name}")

        img=RawFits(p)
        try:
            overview,step=img.overview()
            region,rx0,ry0=img.crop(cx,cy,REGION_HALF)
            zoom,zx0,zy0=img.crop(cx,cy,ZOOM_HALF)

            safe=f"{cid}_{i:02d}_{role.replace('/','_').replace(';','_').replace(' ','_')}"
            ovp=ASSET/f"{safe}_overview.bmp"
            regp=ASSET/f"{safe}_region_marked.bmp"
            zmp=ASSET/f"{safe}_zoom_marked.bmp"
            zup=ASSET/f"{safe}_zoom_unmarked.bmp"

            rgb=to_rgb(overview)
            draw_marker(rgb,cx/step,cy/step,box_half=max(4,256/step))
            write_bmp(rgb,ovp)

            rgb=to_rgb(region)
            draw_marker(rgb,cx-rx0,cy-ry0,box_half=256)
            write_bmp(rgb,regp)

            rgb=to_rgb(zoom)
            draw_marker(rgb,cx-zx0,cy-zy0)
            write_bmp(rgb,zmp)

            write_bmp(to_rgb(zoom),zup)

            skey=(cid,role,pid,sid)
            s=scores.get(skey,{})

            records.append({
                "raw_match_row":cid,
                "panel_role":role,
                "observatory":norm(r.get("observatory")),
                "physical_plate_id":pid,
                "scan_id":sid,
                "gap_hours":norm(r.get("gap_hours")),
                "relation_to_common_overlap":norm(r.get("relation_to_common_overlap")),
                "target_pixel_x":cx,
                "target_pixel_y":cy,
                "fits_path":str(p),
                "fits_sha256":sha(p),
                "fits_shape":[img.nx,img.ny],
                "blind_code":norm(s.get("blind_code")),
                "manual_feature":norm(s.get("feature_at_crosshair")),
                "manual_morphology":norm(s.get("morphology")),
                "manual_confidence":norm(s.get("confidence_1_to_5")),
                "manual_notes":norm(s.get("notes")),
                "assets":{
                    "overview":ovp.name,
                    "region":regp.name,
                    "zoom_marked":zmp.name,
                    "zoom_unmarked":zup.name
                }
            })
        finally:
            img.close()

    MANIFEST.write_text(
        json.dumps({
            "status":"COMPLETE",
            "analysis_kind":"pair17_dual_stellar_original_plate_review_v090",
            "contract_sha256":EXPECTED_CONTRACT_SHA,
            "candidates":list(CANDIDATES),
            "panels":len(records),
            "records":records,
            "display_only":True,
            "candidate_dispositions_changed":False
        },indent=2,sort_keys=True)+"\n",
        encoding="utf-8"
    )

    style="""
    body{font-family:system-ui,sans-serif;background:#101010;color:#eee;margin:24px}
    .intro{max-width:1250px;color:#ccc;line-height:1.45}
    .candidate{margin-top:40px}
    .card{border:1px solid #444;border-radius:10px;padding:16px;margin:18px 0;background:#181818}
    .meta{font-family:ui-monospace,monospace;font-size:12px;white-space:pre-wrap;color:#bbb}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px;margin-top:12px}
    img{width:100%;height:auto;border:1px solid #333;background:#000;image-rendering:auto}
    .label{font-size:12px;color:#aaa;margin:3px 0 7px}
    """

    h=[
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Pair 17 dual-stellar original plate review v090</title>",
        f"<style>{style}</style></head><body>",
        "<h1>Pair 17 — dual-stellar original plate review v090</h1>",
        "<p class='intro'>Candidates 293470, 294052, 294130 and 294179. "
        "Every already-selected v083b panel for these candidates is shown from the original FITS scan. "
        "The overview is a strided raw display; region and zoom views use native pixels. "
        "Each panel uses its own linear 0.5–99.5 percentile stretch. No filtering, subtraction, smoothing, "
        "source detection, or candidate-state change is performed.</p>"
    ]

    current=None
    for rec in records:
        cid=rec["raw_match_row"]
        if cid!=current:
            current=cid
            h.append(f"<div class='candidate'><h2>Candidate {cid}</h2></div>")

        score=(
            f"{rec['blind_code']} — {rec['manual_feature']} / {rec['manual_morphology']} "
            f"/ confidence {rec['manual_confidence']}"
            if rec["blind_code"] else "not joined"
        )
        meta=(
            f"Role: {rec['panel_role']}\n"
            f"Observatory: {rec['observatory']}\n"
            f"Physical plate: {rec['physical_plate_id']}    Scan: {rec['scan_id']}\n"
            f"Relation: {rec['relation_to_common_overlap']}    gap_hours: {rec['gap_hours']}\n"
            f"Target pixel: x={rec['target_pixel_x']:.6f}, y={rec['target_pixel_y']:.6f}\n"
            f"Blind review: {score}\n"
            f"Notes: {rec['manual_notes']}\n"
            f"FITS: {rec['fits_path']}"
        )
        a=rec["assets"]
        h += [
            "<div class='card'>",
            f"<h3>{rec['panel_role']}</h3>",
            f"<div class='meta'>{meta}</div>",
            "<div class='grid'>",
            f"<div><div class='label'>Full original plate — marked</div><img src='assets/{a['overview']}'></div>",
            f"<div><div class='label'>Raw 2048 px region — marked</div><img src='assets/{a['region']}'></div>",
            f"<div><div class='label'>Raw 512 px zoom — marked</div><img src='assets/{a['zoom_marked']}'></div>",
            f"<div><div class='label'>Raw 512 px zoom — unmarked</div><img src='assets/{a['zoom_unmarked']}'></div>",
            "</div></div>"
        ]

    h.append("</body></html>")
    index=OUT/"index.html"
    index.write_text("\n".join(h),encoding="utf-8")

    print()
    print("="*120)
    print("v090 ORIGINAL-PLATE REVIEW VIEWER COMPLETE")
    print("="*120)
    print("Panels:",len(records))
    print(index)
    print("STAGE STATUS: COMPLETE")


if __name__=="__main__":
    main()
