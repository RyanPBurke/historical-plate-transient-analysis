#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from collections import Counter,defaultdict,OrderedDict
from datetime import datetime
import argparse,csv,hashlib,json,math
import numpy as np
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"research"/"prospective_freezes"/"applause_dr4_different_gaia_concentration_astrometry_contract_v094k.json"
PROV=ROOT/"research"/"prospective_freezes"/"applause_dr4_different_gaia_concentration_astrometry_parent_provenance_v094k.json"
EXPECTED_CONTRACT_SHA="0ad18dbe9f2110ee759118d266514bb435de81beecbaa3c712ec97fdd5d51982"
RESULT=ROOT/"results"/"applause_dr4_different_gaia_concentration_astrometry_audit_v094k"

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""): h.update(b)
    return h.hexdigest()
def log(s=""): print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {s}",flush=True)
def rows(p):
    with Path(p).open("r",encoding="utf-8-sig",newline="") as f: yield from csv.DictReader(f)
def fnum(v):
    try:
        x=float(str(v if v is not None else "").strip()); return x if math.isfinite(x) else None
    except:return None
def inum(v):
    x=fnum(v)
    if x is None:return None
    r=int(round(x));return r if abs(x-r)<1e-7 else None
def parse_poly(v):
    import re
    nums=[float(x) for x in re.findall(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',str(v or ""))]
    if len(nums)<8:return None
    nums=nums[-8:];p=[(nums[i]%360.0,nums[i+1]) for i in range(0,8,2)]
    return None if any(not(-90<=d<=90) for _,d in p) else p
def xyz(ra,dec):
    ra=np.deg2rad(np.asarray(ra,float));dec=np.deg2rad(np.asarray(dec,float));c=np.cos(dec)
    return np.column_stack((c*np.cos(ra),c*np.sin(ra),np.sin(dec)))
def arcsec_from_chord(d):
    d=np.clip(np.asarray(d,float),0.0,2.0);return np.degrees(2*np.arcsin(d/2))*3600.0
def tangent_center(polys):
    xs=ys=zs=0.0
    for poly in polys:
        for ra,dec in poly:
            r,d=math.radians(ra),math.radians(dec);c=math.cos(d)
            xs+=c*math.cos(r);ys+=c*math.sin(r);zs+=math.sin(d)
    return math.degrees(math.atan2(ys,xs))%360.0,math.degrees(math.atan2(zs,math.hypot(xs,ys)))
def project_points(ra,dec,ra0,dec0):
    r=np.deg2rad(np.asarray(ra,float));d=np.deg2rad(np.asarray(dec,float))
    r0=math.radians(ra0);d0=math.radians(dec0);dr=(r-r0+math.pi)%(2*math.pi)-math.pi
    cosc=math.sin(d0)*np.sin(d)+math.cos(d0)*np.cos(d)*np.cos(dr)
    ok=cosc>1e-10;x=np.full(len(r),np.nan);y=np.full(len(r),np.nan)
    x[ok]=np.cos(d[ok])*np.sin(dr[ok])/cosc[ok]
    y[ok]=(math.cos(d0)*np.sin(d[ok])-math.sin(d0)*np.cos(d[ok])*np.cos(dr[ok]))/cosc[ok]
    return x,y,ok
def project_poly(poly,ra0,dec0):
    ra=np.asarray([q[0] for q in poly]);dec=np.asarray([q[1] for q in poly]);x,y,ok=project_points(ra,dec,ra0,dec0)
    return None if not np.all(ok) else list(zip(x.tolist(),y.tolist()))
def inside_projected(x,y,poly):
    if poly is None:return np.zeros(len(x),dtype=bool)
    px=np.asarray([p[0] for p in poly]);py=np.asarray([p[1] for p in poly])
    inside=np.zeros(len(x),dtype=bool);j=len(px)-1;valid=np.isfinite(x)&np.isfinite(y)
    for i in range(len(px)):
        yi,yj=py[i],py[j];cross=((yi>y)!=(yj>y))&valid;den=yj-yi
        if abs(den)>1e-20:
            xcross=(px[j]-px[i])*(y-yi)/den+px[i];inside^=cross&(x<xcross)
        j=i
    return inside
def common_mask(ra,dec,pa,pb):
    ra0,dec0=tangent_center([pa,pb]);x,y,ok=project_points(ra,dec,ra0,dec0)
    return ok&inside_projected(x,y,project_poly(pa,ra0,dec0))&inside_projected(x,y,project_poly(pb,ra0,dec0))
def subset(x,m): return {k:v[m] for k,v in x.items() if hasattr(v,'__len__') and len(v)==len(m)}
def mutual_geometry(a,b):
    na,nb=len(a["source_id"]),len(b["source_id"]);out=[]
    if na==0 or nb==0:return out
    xa,xb=xyz(a["ra"],a["dec"]),xyz(b["ra"],b["dec"]);ta,tb=cKDTree(xa),cKDTree(xb)
    da,ib=tb.query(xa,k=1);db,ia=ta.query(xb,k=1);ss=arcsec_from_chord(da)
    for i,j in enumerate(ib.astype(int)):
        if j<nb and int(ia[j])==i:out.append((i,j,float(ss[i])))
    return out
def sepbin(x):
    x=float(x)
    if x<=1:return "LE1"
    if x<=3:return "GT1_LE3"
    if x<=5:return "GT3_LE5"
    if x<=10:return "GT5_LE10"
    if x<=30:return "GT10_LE30"
    if x<=60:return "GT30_LE60"
    return "GT60"
def gaiabin(x):
    if x is None or not math.isfinite(float(x)):return "MISSING"
    x=float(x)
    if x<=.5:return "LE0P5"
    if x<=1:return "GT0P5_LE1"
    if x<=2:return "GT1_LE2"
    if x<=5:return "GT2_LE5"
    return "GT5"
def ratiobin(d,r):
    if d is None or r is None or not math.isfinite(float(d)) or not math.isfinite(float(r)) or float(r)<=0:return "MISSING_OR_INVALID"
    x=float(d)/float(r)
    if x<=.25:return "LE0P25"
    if x<=.5:return "GT0P25_LE0P5"
    if x<=.75:return "GT0P5_LE0P75"
    if x<=1:return "GT0P75_LE1"
    return "GT1"
def neighbin(x):
    try:x=int(x)
    except:return "MISSING"
    if x<0:return "MISSING"
    if x==0:return "0"
    if x==1:return "1"
    if x<=3:return "2_3"
    return "4PLUS"
def nnbin(x):
    if x is None or not math.isfinite(float(x)):return "MISSING"
    x=float(x)
    if x<=3:return "LE3"
    if x<=5:return "GT3_LE5"
    if x<=10:return "GT5_LE10"
    if x<=30:return "GT10_LE30"
    return "GT30"
def wrap_delta_deg(x):
    return (x+180.0)%360.0-180.0
def offset_arcsec(ra1,dec1,ra2,dec2):
    md=0.5*(float(dec1)+float(dec2))
    dx=wrap_delta_deg(float(ra2)-float(ra1))*math.cos(math.radians(md))*3600.0
    dy=(float(dec2)-float(dec1))*3600.0
    return dx,dy
def gini(vals):
    a=np.asarray([float(x) for x in vals if x>=0],float)
    if len(a)==0 or np.sum(a)==0:return 0.0
    a=np.sort(a);n=len(a);return float((2*np.sum((np.arange(1,n+1))*a)/(n*np.sum(a)))-((n+1)/n))
def concentration(counter):
    vals=sorted((int(v) for v in counter.values() if int(v)>0),reverse=True);tot=sum(vals)
    return {
      "nonzero_group_count":len(vals),"total":tot,
      "top1_count":vals[0] if vals else 0,"top1_share":(vals[0]/tot if vals and tot else 0),
      "top5_count":sum(vals[:5]),"top5_share":(sum(vals[:5])/tot if tot else 0),
      "top10_count":sum(vals[:10]),"top10_share":(sum(vals[:10])/tot if tot else 0),
      "gini":gini(vals)
    }
def rb(v,edges=(.5,1,2,3,5)):
    x=float(v)
    if x<=edges[0]:return "LE0P5"
    if x<=edges[1]:return "GT0P5_LE1"
    if x<=edges[2]:return "GT1_LE2"
    if x<=edges[3]:return "GT2_LE3"
    if x<=edges[4]:return "GT3_LE5"
    return "GT5"
def self_test():
    a={"source_id":np.array([1,2]),"ra":np.array([0.,1.]),"dec":np.array([0.,0.])}
    b={"source_id":np.array([3,4]),"ra":np.array([.0001,1.0001]),"dec":np.array([0.,0.])}
    p=mutual_geometry(a,b);assert len(p)==2 and p[0][2]<1
    dx,dy=offset_arcsec(0,0,.001,0);assert abs(dx-3.6)<1e-3 and abs(dy)<1e-9
    c=Counter({"a":10,"b":2,"c":1});z=concentration(c);assert z["top1_count"]==10 and z["total"]==13
    print("v094k self-test PASS");return 0

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
    if a.self_test:return self_test()
    if not CONTRACT.is_file() or sha(CONTRACT)!=EXPECTED_CONTRACT_SHA:raise SystemExit("v094k contract SHA mismatch")
    if not PROV.is_file():raise SystemExit("Missing frozen v094k provenance")
    prov=json.loads(PROV.read_text(encoding="utf-8"))
    if prov.get("status")!="PARENT_PROVENANCE_PREPARED_BEFORE_V094K_SOURCE_MECHANISM_AUDIT":raise SystemExit("Bad v094k provenance status")
    for sec,key,hkey in (
      ("v094j_results","report","report_sha256"),("v094j_results","manifest","manifest_sha256"),
      ("v094j_results","per_opportunity","per_opportunity_sha256"),("v094j_results","site_summary","site_summary_sha256"),
      ("v094j_results","timing_epoch_summary","timing_epoch_summary_sha256"),
      ("frozen_plan","path","sha256"),("source_cache_inventory","path","sha256"),
      ("v094d_solution_full","path","sha256")
    ):
        rec=prov[sec];p=ROOT/rec[key]
        if not p.is_file() or sha(p)!=rec[hkey]:raise SystemExit(f"Frozen parent mismatch: {sec}.{key}")

    plan=list(rows(ROOT/prov["frozen_plan"]["path"]))
    inv=list(rows(ROOT/prov["source_cache_inventory"]["path"]))
    if len(plan)!=1240 or len(inv)!=1386:raise SystemExit("Frozen v094k population size mismatch")
    keypath={}
    for i,r in enumerate(inv,1):
        k=(inum(r["scan_id"]),inum(r["solution_num"]));p=ROOT/r["relative_path"]
        if None in k or not p.is_file() or p.stat().st_size!=int(r["size_bytes"]) or sha(p)!=r["sha256"]:
            raise SystemExit(f"Frozen source cache mismatch at inventory row {i}")
        keypath[k]=p
        if i%200==0:log(f"source-cache verification: {i}/1386")

    # solution polygons
    polys={}
    for r in rows(ROOT/prov["v094d_solution_full"]["path"]):
        sid=inum(r.get("solution_id"));p=parse_poly(r.get("stc_polygon"))
        if sid is not None and p is not None:polys[sid]=p

    cache=OrderedDict()
    def get(k):
        if k in cache:cache.move_to_end(k);return cache[k]
        z=np.load(keypath[k],allow_pickle=False);x={q:np.asarray(z[q]) for q in z.files if not q.endswith("_scalar")}
        cache[k]=x
        while len(cache)>10:cache.popitem(last=False)
        return x

    glob=Counter();siteagg=defaultdict(Counter);teagg=defaultdict(Counter)
    opp_counts=Counter();platepair=Counter();scanpair=Counter()
    source_incidence=Counter();sourcepair_incidence=Counter()
    opp_astrometric_rows=[]
    # per-opportunity counts are retained internally only; result tables emit distributions/ranks without IDs.
    for ix,r in enumerate(plan,1):
        ka=(inum(r["scan_id_a"]),inum(r["solution_num_a"]));kb=(inum(r["scan_id_b"]),inum(r["solution_num_b"]))
        sa,sb=inum(r["solution_id_a"]),inum(r["solution_id_b"]);pa,pb=polys.get(sa),polys.get(sb)
        if pa is None or pb is None:raise SystemExit("Missing selected solution polygon")
        A,B=get(ka),get(kb)
        Ac=subset(A,common_mask(A["ra"],A["dec"],pa,pb));Bc=subset(B,common_mask(B["ra"],B["dec"],pa,pb))
        mp=mutual_geometry(Ac,Bc)
        same_ref=[];diff5=[]
        c=Counter()
        for ia,ib,ss in mp:
            g1,g2=int(Ac["gaia_id"][ia]),int(Bc["gaia_id"][ib])
            ident="SAME_GAIA" if g1>0 and g2>0 and g1==g2 else ("DIFFERENT_GAIA" if g1>0 and g2>0 else "GAIA_UNRESOLVED")
            if ident=="SAME_GAIA" and ss<=60:
                dx,dy=offset_arcsec(Ac["ra"][ia],Ac["dec"][ia],Bc["ra"][ib],Bc["dec"][ib]);same_ref.append((dx,dy))
            if ident!="DIFFERENT_GAIA":continue
            c["diff_total"]+=1;c[f"diff_sep_{sepbin(ss)}"]+=1
            if ss<=60:c["diff_le60"]+=1
            if ss<=5:
                c["diff_le5"]+=1
                da=fnum(Ac["gaiaedr3_dist"][ia]);db=fnum(Bc["gaiaedr3_dist"][ib])
                ma=fnum(Ac["match_radius"][ia]);mb=fnum(Bc["match_radius"][ib])
                nga=inum(Ac["gaiaedr3_neighbors"][ia]);ngb=inum(Bc["gaiaedr3_neighbors"][ib])
                nna=fnum(Ac["nn_dist"][ia]);nnb=fnum(Bc["nn_dist"][ib])
                c[f"end_gaia_dist_{gaiabin(da)}"]+=1;c[f"end_gaia_dist_{gaiabin(db)}"]+=1
                c[f"end_gaia_ratio_{ratiobin(da,ma)}"]+=1;c[f"end_gaia_ratio_{ratiobin(db,mb)}"]+=1
                c[f"end_gaia_neighbors_{neighbin(nga)}"]+=1;c[f"end_gaia_neighbors_{neighbin(ngb)}"]+=1
                c[f"end_nn_dist_{nnbin(nna)}"]+=1;c[f"end_nn_dist_{nnbin(nnb)}"]+=1
                if da is not None and db is not None:
                    if da<=1 and db<=1:c["both_own_gaia_le1"]+=1
                    if ss<da and ss<db:c["pair_closer_than_both_own_gaia"]+=1
                sid1=int(Ac["source_id"][ia]);sid2=int(Bc["source_id"][ib])
                source_incidence[sid1]+=1;source_incidence[sid2]+=1
                sourcepair_incidence[tuple(sorted((sid1,sid2)))] += 1
                dx,dy=offset_arcsec(Ac["ra"][ia],Ac["dec"][ia],Bc["ra"][ib],Bc["dec"][ib])
                diff5.append((dx,dy))
        # fixed empirical astrometric-reference diagnostic
        if len(same_ref)>=20:
            ar=np.asarray(same_ref,float);mx,my=np.median(ar[:,0]),np.median(ar[:,1])
            scat=float(np.median(np.hypot(ar[:,0]-mx,ar[:,1]-my)))
            c["astrometric_reference_eligible"]=1;c["same_gaia_reference_pairs"]=len(same_ref)
            c[f"same_gaia_reference_scatter_{rb(scat)}"]+=1
            for dx,dy in diff5:
                res=math.hypot(dx-mx,dy-my);c[f"diff_le5_compensated_residual_{rb(res)}"]+=1
        elif diff5:
            c["astrometric_reference_insufficient_for_diff_opportunity"]=1
        # concentration group counters
        n5=c["diff_le5"];opp_key=ix
        opp_counts[opp_key]=n5
        pp=tuple(sorted((inum(r["plate_a"]),inum(r["plate_b"]))))
        sp=tuple(sorted((ka,kb)))
        platepair[pp]+=n5;scanpair[sp]+=n5
        site=r["site_pair"];te=f"{r['timing_bin']}|{r['epoch_label']}"
        for k,v in c.items():
            glob[k]+=v;siteagg[site][k]+=v;teagg[te][k]+=v
        glob["opportunities"]+=1;siteagg[site]["opportunities"]+=1;teagg[te]["opportunities"]+=1
        if ix%100==0:log(f"v094k mechanism audit: {ix}/1240")

    # mechanical consistency with frozen v094j
    expected=prov["known_v094j_outcomes"]
    if glob["diff_le5"]!=int(expected["mutual_different_gaia_le5"]):
        raise SystemExit(f"Mechanical consistency HOLD: diff<=5 {glob['diff_le5']} != {expected['mutual_different_gaia_le5']}")
    if glob["diff_le60"]!=int(expected["mutual_different_gaia_le60"]):
        raise SystemExit(f"Mechanical consistency HOLD: diff<=60 {glob['diff_le60']} != {expected['mutual_different_gaia_le60']}")
    if glob["pair_closer_than_both_own_gaia"]!=int(expected["pair_closer_than_both_own_gaia_le5"]):
        raise SystemExit("Mechanical consistency HOLD: pair-closer-than-own-Gaia count mismatch")

    RESULT.mkdir(parents=True,exist_ok=True)
    def writeagg(path,d):
        fields=["group"]+sorted({k for c in d.values() for k in c})
        with path.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
            for g,c in sorted(d.items(),key=lambda kv:(-kv[1].get("diff_le5",0),kv[0])):
                rr={"group":g};rr.update(c);w.writerow(rr)
    sitep=RESULT/"site_pair_mechanism_summary_v094k.csv";tep=RESULT/"timing_epoch_mechanism_summary_v094k.csv"
    writeagg(sitep,siteagg);writeagg(tep,teagg)

    # Opportunity-count histogram and anonymized concentration ranks.
    bins=[("ZERO",0,0),("ONE",1,1),("TWO_TO_FIVE",2,5),("SIX_TO_20",6,20),
          ("GT20_TO100",21,100),("GT100_TO500",101,500),("GT500",501,10**18)]
    hist=[]
    vals=list(opp_counts.values())
    for name,lo,hi in bins:
        vv=[x for x in vals if lo<=x<=hi]
        hist.append({"bin":name,"opportunities":len(vv),"different_gaia_le5_pairs":sum(vv)})
    histp=RESULT/"opportunity_different_gaia_count_distribution_v094k.csv"
    with histp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["bin","opportunities","different_gaia_le5_pairs"]);w.writeheader();w.writerows(hist)

    concs={"opportunity":concentration(opp_counts),"physical_plate_pair":concentration(platepair),
           "exact_scan_solution_pair":concentration(scanpair)}
    rankp=RESULT/"anonymized_concentration_rank_summary_v094k.csv"
    with rankp.open("w",encoding="utf-8",newline="") as f:
        fields=["group_type","rank","different_gaia_le5_count","share_of_all_different_gaia_le5"]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for name,cnt in (("opportunity",opp_counts),("physical_plate_pair",platepair),("exact_scan_solution_pair",scanpair)):
            top=sorted(cnt.values(),reverse=True)[:20]
            for rank,v in enumerate(top,1):
                w.writerow({"group_type":name,"rank":rank,"different_gaia_le5_count":v,
                            "share_of_all_different_gaia_le5":v/glob["diff_le5"] if glob["diff_le5"] else 0})

    # source reuse is aggregate-only
    sincid=sum(source_incidence.values());suniq=len(source_incidence)
    pincid=sum(sourcepair_incidence.values());puniq=len(sourcepair_incidence)
    reuse={
      "different_gaia_le5_endpoint_incidences":sincid,
      "unique_source_ids_internal_only":suniq,
      "repeated_source_endpoint_incidences":sincid-suniq,
      "repeated_source_endpoint_incidence_fraction":None if not sincid else (sincid-suniq)/sincid,
      "sources_used_more_than_once":sum(1 for v in source_incidence.values() if v>1),
      "max_source_role_reuse":max(source_incidence.values(),default=0),
      "different_gaia_le5_pair_incidences":pincid,
      "unique_source_pairs_internal_only":puniq,
      "repeated_source_pair_incidences":pincid-puniq,
      "repeated_source_pair_incidence_fraction":None if not pincid else (pincid-puniq)/pincid,
      "source_pairs_reused_more_than_once":sum(1 for v in sourcepair_incidence.values() if v>1),
      "max_source_pair_reuse":max(sourcepair_incidence.values(),default=0)
    }
    report={
      "status":"COMPLETE",
      "analysis_kind":"applause_dr4_different_gaia_concentration_astrometry_audit_v094k",
      "contract_sha256":EXPECTED_CONTRACT_SHA,
      "parent_provenance_sha256":sha(PROV),
      "opportunities":1240,
      "aggregate":dict(glob),
      "concentration":concs,
      "source_reuse":reuse,
      "site_pair_summary":{g:dict(c) for g,c in sorted(siteagg.items(),key=lambda kv:(-kv[1]["diff_le5"],kv[0]))},
      "timing_epoch_summary":{g:dict(c) for g,c in sorted(teagg.items(),key=lambda kv:(-kv[1]["diff_le5"],kv[0]))},
      "guards":{"network_queries":0,"external_gaia_queries":0,"controls":0,"pixels":0,"fits":0,
                "registration":0,"coordinate_corrections_written":0,"physical_parallax_pairing":0,
                "source_quality_threshold_relaxation":0,"candidate_inspection":0,
                "source_or_gaia_ids_emitted":0,"coordinates_emitted":0,"individual_opportunity_ids_emitted":0},
      "interpretive_stop":"Interpret concentration, crowding/Gaia association, source reuse, and same-Gaia-referenced astrometric residuals before parallax or quality relaxation."
    }
    rp=RESULT/"applause_dr4_different_gaia_concentration_astrometry_audit_v094k.json"
    report["output_hashes"]={p.name:sha(p) for p in (sitep,tep,histp,rankp)}
    rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    man=RESULT/"v094k_output_manifest.sha256"
    man.write_text("".join(f"{sha(p)}  {p.name}\n" for p in (sitep,tep,histp,rankp,rp)),encoding="utf-8")

    comp=sum(glob[k] for k in ("diff_le5_compensated_residual_LE0P5","diff_le5_compensated_residual_GT0P5_LE1"))
    print("\n"+"="*100)
    print("v094k DIFFERENT-GAIA CONCENTRATION / ASTROMETRIC-MECHANISM AUDIT COMPLETE")
    print("="*100)
    print(f"Opportunities processed:                         {glob['opportunities']}")
    print(f"DIFFERENT_GAIA mutual pairs <=5 arcsec:         {glob['diff_le5']:,}")
    print(f"DIFFERENT_GAIA mutual pairs <=60 arcsec:        {glob['diff_le60']:,}")
    print(f"Pair closer than both own Gaia <=5 arcsec:      {glob['pair_closer_than_both_own_gaia']:,}")
    print(f"Both endpoints own-Gaia <=1 arcsec:             {glob['both_own_gaia_le1']:,}")
    print(f"Opportunities with >=20 same-Gaia refs:         {glob['astrometric_reference_eligible']}")
    print(f"DIFFERENT_GAIA <=5 with compensated residual <=1 arcsec: {comp:,}")
    print(f"Opportunity top-1 share of diff-Gaia <=5:       {concs['opportunity']['top1_share']}")
    print(f"Opportunity top-5 share of diff-Gaia <=5:       {concs['opportunity']['top5_share']}")
    print(f"Plate-pair top-1 share of diff-Gaia <=5:        {concs['physical_plate_pair']['top1_share']}")
    print(f"Scan/solution-pair top-1 share <=5:             {concs['exact_scan_solution_pair']['top1_share']}")
    print(f"Repeated source endpoint incidence fraction:    {reuse['repeated_source_endpoint_incidence_fraction']}")
    print(f"Repeated source-pair incidence fraction:        {reuse['repeated_source_pair_incidence_fraction']}")
    print("Network / controls / pixels / registration:    0 / 0 / 0 / 0")
    print("Candidate/source/Gaia IDs emitted:             0")
    print("STOP: interpret mechanism before physical parallax, threshold relaxation, or individual inspection.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
