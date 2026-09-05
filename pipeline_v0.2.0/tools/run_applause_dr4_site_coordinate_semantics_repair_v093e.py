#!/usr/bin/env python3
from pathlib import Path
from collections import Counter
import csv, hashlib, json, math

ROOT = Path(__file__).resolve().parents[1]

CONTRACT = ROOT/"research"/"prospective_freezes"/"applause_dr4_site_coordinate_semantics_repair_contract_v093e.json"
EXPECTED_CONTRACT_SHA = "6f6bfb433ddd4674f85ea6de02e278b5eb47e0706bc9cbccc899824e64455742"

PARENT = ROOT/"results"/"applause_dr4_plate_site_provenance_refinement_v093d"
BANK = PARENT/"applause_dr4_v093d_bank_manifest.json"
EXPECTED_BANK_SHA = "246a765bf5bd7782f754791610389758d7a62b32cfea367924d52ec8907554e5"

OPP = PARENT/"applause_dr4_plate_site_refined_opportunities_v093d.csv"
COMP = PARENT/"applause_dr4_plate_site_refined_comparisons_v093d.csv"

OUT = ROOT/"results"/"applause_dr4_site_coordinate_semantics_repair_v093e"

SITE_RULES = {
    "Dr. Remeis-Observatory, Bamberg, Germany": "SWAP",
    "Hamburg-Bergedorf, Germany": "NORMAL",
    "Bonn, Germany": "NORMAL",
    "Castel Gandolfo, Italy": "NORMAL",
    "Boyden Observatory, Bloemfontein, South Africa": "NORMAL",
    "Potsdam-Telegrafenberg": "NORMAL",
    "Mount John Observatory, Lake Tekapo, New Zealand": "NORMAL",
}

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def rows(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f:
        yield from csv.DictReader(f)

def wcsv(p,rr,fields):
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader()
        for r in rr:w.writerow(r)
    tmp.replace(p)

def fnum(v):
    try:
        x=float(str(v or "").strip())
        return x if math.isfinite(x) else None
    except:
        return None

def corrected(site, lon, lat):
    if site not in SITE_RULES:
        raise RuntimeError(f"Unfrozen site encountered: {site!r}")
    if lon is None or lat is None:
        return None,None
    if SITE_RULES[site]=="SWAP":
        return lat,lon
    return lon,lat

def hav_km(lat1,lon1,lat2,lon2):
    if None in (lat1,lon1,lat2,lon2):return None
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 6371.0088*2*math.atan2(math.sqrt(a),math.sqrt(max(0.0,1-a)))

def band(d):
    if d is None:return "COORDS_INCOMPLETE"
    if d<1:return "LT1KM"
    if d<10:return "GE1_LT10KM"
    if d<50:return "GE10_LT50KM"
    if d<100:return "GE50_LT100KM"
    return "GE100KM"

def boolish(v):
    return str(v or "").strip().lower() in {"true","1","yes"}

def main():
    print("="*110)
    print("APPLAUSE DR4 — SITE COORDINATE SEMANTICS REPAIR v093e")
    print("="*110)
    print("Geographic-coordinate repair only; science/cadence population unchanged.")
    print("Network/source/pixel/detector calls: 0")
    print()

    if sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:
        raise RuntimeError("v093e contract SHA mismatch")
    if sha(BANK)!=EXPECTED_BANK_SHA:
        raise RuntimeError("v093d bank manifest SHA mismatch")

    bank=json.loads(BANK.read_text(encoding="utf-8"))
    bank_files={x["name"]:x["sha256"] for x in bank.get("files",[])}
    for p in (OPP,COMP):
        exp=bank_files.get(p.name)
        if not exp or sha(p)!=exp:
            raise RuntimeError(f"Banked v093d input SHA mismatch: {p.name}")

    out_rows=[]
    site_pairs=Counter()
    bands=Counter()
    tiers10=Counter(); tiers50=Counter(); tiers100=Counter()
    minmax={}
    unique_phys10=set()
    unique_phys50=set()
    unique_phys100=set()

    for r in rows(OPP):
        sa=str(r.get("plate_site_a") or "").strip()
        sb=str(r.get("plate_site_b") or "").strip()

        raw_lat_a=fnum(r.get("plate_site_lat_a"))
        raw_lon_a=fnum(r.get("plate_site_lon_a"))
        raw_lat_b=fnum(r.get("plate_site_lat_b"))
        raw_lon_b=fnum(r.get("plate_site_lon_b"))

        lon_a,lat_a=corrected(sa,raw_lon_a,raw_lat_a)
        lon_b,lat_b=corrected(sb,raw_lon_b,raw_lat_b)

        d=hav_km(lat_a,lon_a,lat_b,lon_b)
        db=band(d)
        bands[db]+=1
        pair=" | ".join(sorted((sa,sb)))
        site_pairs[pair]+=1
        if d is not None:
            mm=minmax.setdefault(pair,[d,d])
            mm[0]=min(mm[0],d); mm[1]=max(mm[1],d)

        strong10=bool(d is not None and d>=10 and sa!=sb)
        strong50=bool(d is not None and d>=50 and sa!=sb)
        strong100=bool(d is not None and d>=100 and sa!=sb)
        tier=str(r.get("best_same_site_control_tier") or "").strip()

        phys=tuple(sorted((str(r.get("plate_a")),str(r.get("plate_b")))))
        if tier and strong10:
            tiers10[tier]+=1; unique_phys10.add(phys)
        if tier and strong50:
            tiers50[tier]+=1; unique_phys50.add(phys)
        if tier and strong100:
            tiers100[tier]+=1; unique_phys100.add(phys)

        x=dict(r)
        x.update({
            "raw_plate_site_lon_a_v093d":r.get("plate_site_lon_a"),
            "raw_plate_site_lat_a_v093d":r.get("plate_site_lat_a"),
            "raw_plate_site_lon_b_v093d":r.get("plate_site_lon_b"),
            "raw_plate_site_lat_b_v093d":r.get("plate_site_lat_b"),
            "corrected_site_lon_a":"" if lon_a is None else f"{lon_a:.8f}",
            "corrected_site_lat_a":"" if lat_a is None else f"{lat_a:.8f}",
            "corrected_site_lon_b":"" if lon_b is None else f"{lon_b:.8f}",
            "corrected_site_lat_b":"" if lat_b is None else f"{lat_b:.8f}",
            "site_coordinate_rule_a":SITE_RULES[sa],
            "site_coordinate_rule_b":SITE_RULES[sb],
            "corrected_site_separation_km":"" if d is None else f"{d:.6f}",
            "corrected_site_separation_band":db,
            "corrected_strong_independence_ge10km":strong10,
            "corrected_independence_ge50km":strong50,
            "corrected_independence_ge100km":strong100,
        })
        out_rows.append(x)

    comp_rows=[]
    for r in rows(COMP):
        ps=str(r.get("positive_site_name") or "").strip()
        cs=str(r.get("comparison_site_name") or "").strip()

        plat=fnum(r.get("positive_site_latitude")); plon=fnum(r.get("positive_site_longitude"))
        clat=fnum(r.get("comparison_site_latitude")); clon=fnum(r.get("comparison_site_longitude"))

        plon2,plat2=corrected(ps,plon,plat)
        clon2,clat2=corrected(cs,clon,clat)

        d=hav_km(plat2,plon2,clat2,clon2)
        x=dict(r)
        x.update({
            "corrected_positive_site_longitude":"" if plon2 is None else f"{plon2:.8f}",
            "corrected_positive_site_latitude":"" if plat2 is None else f"{plat2:.8f}",
            "corrected_comparison_site_longitude":"" if clon2 is None else f"{clon2:.8f}",
            "corrected_comparison_site_latitude":"" if clat2 is None else f"{clat2:.8f}",
            "corrected_control_site_separation_km":"" if d is None else f"{d:.6f}",
        })
        comp_rows.append(x)

    OUT.mkdir(parents=True,exist_ok=True)
    opp_out=OUT/"applause_dr4_site_coordinate_repaired_opportunities_v093e.csv"
    comp_out=OUT/"applause_dr4_site_coordinate_repaired_comparisons_v093e.csv"
    if out_rows:wcsv(opp_out,out_rows,list(out_rows[0].keys()))
    if comp_rows:wcsv(comp_out,comp_rows,list(comp_rows[0].keys()))

    pair_distances={
        k:{
            "occurrences":site_pairs[k],
            "min_km":round(v[0],6),
            "max_km":round(v[1],6)
        } for k,v in sorted(minmax.items())
    }

    report={
        "status":"COMPLETE",
        "analysis_kind":"applause_dr4_site_coordinate_semantics_repair_v093e",
        "contract_sha256":EXPECTED_CONTRACT_SHA,
        "parent_v093d_bank_manifest_sha256":EXPECTED_BANK_SHA,
        "opportunity_rows":len(out_rows),
        "comparison_rows":len(comp_rows),
        "site_pair_occurrences":dict(site_pairs),
        "corrected_site_pair_distance_ranges_km":pair_distances,
        "corrected_site_separation_band_counts":dict(bands),
        "corrected_ge10km_best_control_tier_counts":dict(tiers10),
        "corrected_ge50km_best_control_tier_counts":dict(tiers50),
        "corrected_ge100km_best_control_tier_counts":dict(tiers100),
        "corrected_ge10km_unique_physical_science_plate_pairs_with_control":len(unique_phys10),
        "corrected_ge50km_unique_physical_science_plate_pairs_with_control":len(unique_phys50),
        "corrected_ge100km_unique_physical_science_plate_pairs_with_control":len(unique_phys100),
        "all_science_site_pairs_ge100km":all(
            v["min_km"]>=100 for v in pair_distances.values()
        ) if pair_distances else False,
        "science_or_cadence_population_changed":False,
        "guards":{
            "network_calls":0,"source_catalog_queries":0,"pixel_downloads":0,
            "fits_reads":0,"detector_runs":0,"candidate_adjudication":0,
            "candidate_disposition_changes":0,"v093d_outputs_modified":False
        },
        "output_hashes":{}
    }
    for p in (opp_out,comp_out):
        report["output_hashes"][p.name]=sha(p)

    rp=OUT/"applause_dr4_site_coordinate_semantics_repair_v093e.json"
    rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")

    print("Opportunity rows:",len(out_rows))
    print("Corrected site bands:",dict(bands))
    print("Corrected >=10 km tiers:",dict(tiers10))
    print("Corrected >=50 km tiers:",dict(tiers50))
    print("Corrected >=100 km tiers:",dict(tiers100))
    print("Corrected >=100 km all site pairs:",report["all_science_site_pairs_ge100km"])
    print("Unique physical science pairs with control:",len(unique_phys100))
    print()
    print("Corrected site-pair distances:")
    for k,v in pair_distances.items():
        print(f"  {k}: {v['min_km']:.3f}–{v['max_km']:.3f} km ({v['occurrences']} rows)")
    print()
    print("REPORT SHA256:",sha(rp))
    print("STAGE STATUS: COMPLETE")

if __name__=="__main__":
    main()
