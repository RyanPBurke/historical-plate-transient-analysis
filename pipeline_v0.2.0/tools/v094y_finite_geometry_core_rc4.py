#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
from itertools import combinations
from fractions import Fraction
from datetime import timedelta
import argparse, hashlib, importlib.util, json, math, os, sys

import numpy as np
from scipy.optimize import linprog

CONTRACT_SHA = "eede026c61e1538f2396f3b6ef5221ed18dba450f18e2f8b7d11f05c093c6a5f"
FROZEN_V094X_SHA = "f75a866e63dfedd24a677acd925d8e4e2a53e34d99e582596e0adb9a3db5e7cc"

# v094y RC4 implementation constants. Their authoritative values are frozen by the RC4 contract.
LP_TOL = 1e-9
WITNESS_RESID_KM = 1e-7
RAY_ZERO_KM = 1e-9
MOTION_BOUND_KM_S = 0.60
REFERENCE_SWITCH_ALLOWANCE_KM = 0.03

WGS84_A_KM = 6378.137
WGS84_F = 1/298.257223563
WGS84_B_KM = WGS84_A_KM*(1-WGS84_F)

@dataclass
class HalfspaceSystem:
    A: np.ndarray  # A @ P >= b
    b: np.ndarray
    labels: list[str]

@dataclass
class FixedTimeResult:
    status: str
    witness: np.ndarray | None
    min_distance_km: float | None
    max_distance_km: float | None
    max_unbounded: bool | None
    lower_closed: bool | None
    upper_closed: bool | None
    farkas_certificate: dict | None
    detail: str

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def unit(v):
    v=np.asarray(v,float)
    n=float(np.linalg.norm(v))
    if not math.isfinite(n) or n<=0:
        raise ValueError("zero/nonfinite vector")
    return v/n

def xyz(ra_deg,dec_deg):
    r=math.radians(float(ra_deg)); d=math.radians(float(dec_deg))
    c=math.cos(d)
    return np.array([c*math.cos(r),c*math.sin(r),math.sin(d)],float)

def radec(v):
    v=unit(v)
    return math.degrees(math.atan2(v[1],v[0]))%360, math.degrees(math.asin(np.clip(v[2],-1,1)))

def tangent_basis(center):
    c=unit(center)
    z=np.array([0.,0.,1.])
    e=np.cross(z,c)
    if np.linalg.norm(e)<1e-10:
        e=np.cross(np.array([1.,0.,0.]),c)
    e=unit(e); n=unit(np.cross(c,e))
    return e,n

def gnomonic_project(v,center):
    v=unit(v); c=unit(center)
    den=float(v@c)
    if den<=1e-10:
        raise ValueError("polygon not contained in one gnomonic hemisphere")
    e,n=tangent_basis(c)
    return np.array([float(v@e)/den,float(v@n)/den])

def orient2(a,b,c):
    # Explicit 2-D scalar cross product. NumPy >=2.0 no longer accepts
    # 2-element vectors in np.cross(); keep this independent of NumPy version.
    a=np.asarray(a,float); b=np.asarray(b,float); c=np.asarray(c,float)
    ab=b-a; ac=c-a
    return float(ab[0]*ac[1]-ab[1]*ac[0])

def polygon_area2(poly2):
    return sum(poly2[i][0]*poly2[(i+1)%len(poly2)][1]-poly2[(i+1)%len(poly2)][0]*poly2[i][1]
               for i in range(len(poly2)))/2

def point_in_triangle_2d(p,a,b,c,tol=1e-12):
    s1=orient2(a,b,p); s2=orient2(b,c,p); s3=orient2(c,a,p)
    hasneg=min(s1,s2,s3)<-tol; haspos=max(s1,s2,s3)>tol
    return not (hasneg and haspos)

def _fpoint2(p):
    p=np.asarray(p,float)
    return (Fraction.from_float(float(p[0])),Fraction.from_float(float(p[1])))

def orient2_exact(a,b,c):
    ax,ay=_fpoint2(a); bx,by=_fpoint2(b); cx,cy=_fpoint2(c)
    return (bx-ax)*(cy-ay)-(by-ay)*(cx-ax)

def _between_exact(x,a,b):
    return min(a,b) <= x <= max(a,b)

def _on_segment_exact(p,a,b):
    if orient2_exact(a,b,p)!=0:return False
    px,py=_fpoint2(p); ax,ay=_fpoint2(a); bx,by=_fpoint2(b)
    return _between_exact(px,ax,bx) and _between_exact(py,ay,by)

def _sgn_fraction(x):
    return 1 if x>0 else (-1 if x<0 else 0)

def segments_intersect_exact(a,b,c,d):
    o1=orient2_exact(a,b,c); o2=orient2_exact(a,b,d)
    o3=orient2_exact(c,d,a); o4=orient2_exact(c,d,b)
    s1,s2,s3,s4=map(_sgn_fraction,(o1,o2,o3,o4))
    if s1*s2<0 and s3*s4<0:return True
    if o1==0 and _on_segment_exact(c,a,b):return True
    if o2==0 and _on_segment_exact(d,a,b):return True
    if o3==0 and _on_segment_exact(a,c,d):return True
    if o4==0 and _on_segment_exact(b,c,d):return True
    return False

def validate_simple_projected_polygon(pp):
    """Reject repeated vertices, collapsed/collinear boundaries and any non-adjacent edge crossing/touch."""
    if len(pp)<3:raise ValueError("polygon needs >=3 projected vertices")
    fp=[_fpoint2(p) for p in pp]
    if len(set(fp))!=len(fp):raise ValueError("repeated polygon vertex")
    n=len(pp)
    for i in range(n):
        a,b=pp[i],pp[(i+1)%n]
        if _fpoint2(a)==_fpoint2(b):raise ValueError("zero-length polygon edge")
        # Boundary degeneracy: three consecutive projected vertices may not be collinear.
        if orient2_exact(pp[i-1],a,b)==0:raise ValueError("collinear/degenerate polygon boundary")
    for i in range(n):
        a,b=pp[i],pp[(i+1)%n]
        for j in range(i+1,n):
            # Adjacent edges are allowed to meet only at their shared declared endpoint.
            if j==i or j==(i+1)%n or i==(j+1)%n:continue
            c,d=pp[j],pp[(j+1)%n]
            if segments_intersect_exact(a,b,c,d):
                raise ValueError(f"self-crossing/non-simple polygon edges {i} and {j}")
    return True

def triangulate_spherical_polygon(vertices):
    """Deterministic ear clipping after validated gnomonic projection. Prototype supports simple 3/4-vertex footprints."""
    vv=[unit(v) for v in vertices]
    if len(vv)<3:
        raise ValueError("polygon needs >=3 vertices")
    c=unit(np.sum(vv,axis=0))
    pp=[gnomonic_project(v,c) for v in vv]
    validate_simple_projected_polygon(pp)
    area=polygon_area2(pp)
    if abs(area)<1e-14:
        raise ValueError("degenerate projected polygon")
    if area<0:
        vv=list(reversed(vv)); pp=list(reversed(pp))
    idx=list(range(len(vv))); tris=[]
    guard=0
    while len(idx)>3:
        guard+=1
        if guard>20:
            raise ValueError("ear clipping failed")
        clipped=False
        for j in range(len(idx)):
            i0,i1,i2=idx[j-1],idx[j],idx[(j+1)%len(idx)]
            a,b,c2=pp[i0],pp[i1],pp[i2]
            if orient2(a,b,c2)<=1e-13:
                continue
            if any(point_in_triangle_2d(pp[k],a,b,c2) for k in idx if k not in (i0,i1,i2)):
                continue
            tris.append([vv[i0],vv[i1],vv[i2]])
            del idx[j]; clipped=True; break
        if not clipped:
            raise ValueError("non-simple or numerically ambiguous polygon")
    tris.append([vv[idx[0]],vv[idx[1]],vv[idx[2]]])
    return tris

def convex_component_edge_normals(vertices):
    vv=[unit(v) for v in vertices]
    c=unit(np.sum(vv,axis=0))
    out=[]
    for i in range(len(vv)):
        a,b=vv[i],vv[(i+1)%len(vv)]
        cr=np.cross(a,b)
        n=float(np.linalg.norm(cr))
        if n<1e-12:
            raise ValueError("zero/180-degree polygon edge")
        e=cr/n
        if float(e@c)<0:
            e=-e
        # Every vertex must lie in/on the same edge halfspace for convexity.
        if min(float(e@q) for q in vv)<-1e-10:
            raise ValueError("component is not convex under great-circle edge semantics")
        out.append(e)
    return out

def component_halfspaces(edge_normals,site_r,site_label):
    A=[];b=[];labels=[]
    r=np.asarray(site_r,float)
    for i,e in enumerate(edge_normals):
        e=unit(e)
        A.append(e); b.append(float(e@r)); labels.append(f"{site_label}:footprint_edge:{i}")
    return HalfspaceSystem(np.asarray(A,float),np.asarray(b,float),labels)

def combine(*systems):
    A=np.vstack([s.A for s in systems]); b=np.concatenate([s.b for s in systems])
    labels=sum((s.labels for s in systems),[])
    return HalfspaceSystem(A,b,labels)

def add_horizon(system,site_r,up,site_label):
    u=unit(up); r=np.asarray(site_r,float)
    return combine(system,HalfspaceSystem(np.array([u]),np.array([float(u@r)]),[f"{site_label}:horizon"]))

def min_residual(system,p):
    return float(np.min(system.A@np.asarray(p,float)-system.b))

def _F(x):
    return Fraction.from_float(float(x))

def exact_dot3(a,b):
    return sum(_F(x)*_F(y) for x,y in zip(np.asarray(a,float),np.asarray(b,float)))

def exact_halfspace_contains(system,p):
    """Exact sign check relative to the actual binary64 A, b and witness coordinates."""
    p=np.asarray(p,float)
    for row,b in zip(np.asarray(system.A,float),np.asarray(system.b,float)):
        lhs=sum(_F(row[j])*_F(p[j]) for j in range(3))
        if lhs < _F(b):
            return False
    return True

def exact_homogeneous_contains(A,d):
    """Exact recession-direction check against frozen binary64 coefficients."""
    d=np.asarray(d,float)
    if all(_F(x)==0 for x in d):
        return False
    for row in np.asarray(A,float):
        lhs=sum(_F(row[j])*_F(d[j]) for j in range(3))
        if lhs < 0:
            return False
    return True

def feasible_lp(system):
    res=linprog(np.zeros(3),A_ub=-system.A,b_ub=-system.b,
                bounds=[(None,None)]*3,method="highs",
                options={"primal_feasibility_tolerance":LP_TOL,
                         "dual_feasibility_tolerance":LP_TOL})
    if res.success:
        p=np.asarray(res.x,float)
        if min_residual(system,p) >= -WITNESS_RESID_KM:
            return "FEASIBLE",p,res
        return "UNRESOLVED",None,res
    if int(res.status)==2:
        return "LP_INFEASIBLE",None,res
    return "UNRESOLVED",None,res

def solve_unique_fraction(M,rhs):
    """Exact rational solve of overdetermined M x = rhs; return None unless unique and exactly consistent."""
    M=[[Fraction(v) for v in row] for row in M]
    rhs=[Fraction(v) for v in rhs]
    aug=[row+[rhs[i]] for i,row in enumerate(M)]
    m=len(aug); n=len(aug[0])-1
    prow=0; pivots=[]
    for col in range(n):
        pivot=None
        for r in range(prow,m):
            if aug[r][col] != 0:
                pivot=r; break
        if pivot is None:
            continue
        aug[prow],aug[pivot]=aug[pivot],aug[prow]
        q=aug[prow][col]
        aug[prow]=[x/q for x in aug[prow]]
        for r in range(m):
            if r==prow: continue
            q=aug[r][col]
            if q:
                aug[r]=[aug[r][j]-q*aug[prow][j] for j in range(n+1)]
        pivots.append((prow,col)); prow+=1
        if prow==m: break
    for r in range(m):
        if all(aug[r][c]==0 for c in range(n)) and aug[r][n]!=0:
            return None
    if len(pivots)!=n:
        return None
    x=[Fraction(0) for _ in range(n)]
    for r,c in pivots:
        x[c]=aug[r][n]
    # exact replay
    for i,row in enumerate(M):
        if sum(row[j]*x[j] for j in range(n)) != rhs[i]:
            return None
    return x

def exact_farkas_certificate(system):
    """Exact certificate relative to the actual IEEE-754 A,b coefficients."""
    A=np.asarray(system.A,float); b=np.asarray(system.b,float); m=len(b)
    # In R^3 an extreme normalized Farkas certificate needs <=4 positive entries.
    for k in range(1,min(4,m)+1):
        for ids in combinations(range(m),k):
            M=[]
            for dim in range(3):
                M.append([Fraction.from_float(float(A[i,dim])) for i in ids])
            M.append([Fraction(1) for _ in ids])
            rhs=[Fraction(0),Fraction(0),Fraction(0),Fraction(1)]
            y=solve_unique_fraction(M,rhs)
            if y is None or any(q<0 for q in y):
                continue
            margin=sum(Fraction.from_float(float(b[i]))*y[j] for j,i in enumerate(ids))
            if margin>0:
                return {
                    "support_indices":list(ids),
                    "support_labels":[system.labels[i] for i in ids],
                    "weights_exact":[f"{q.numerator}/{q.denominator}" for q in y],
                    "margin_exact":f"{margin.numerator}/{margin.denominator}",
                    "margin_float_km":float(margin),
                    "meaning":"Exact Farkas infeasibility certificate for the frozen binary64 halfspace coefficients."
                }
    return None

def exact_farkas_certificate_for_support(system,ids):
    try:ids=[int(x) for x in ids]
    except:return None
    A=np.asarray(system.A,float);b=np.asarray(system.b,float);m=len(b)
    if not ids or len(ids)>4 or len(set(ids))!=len(ids) or min(ids)<0 or max(ids)>=m:return None
    M=[]
    for dim in range(3):M.append([Fraction.from_float(float(A[i,dim])) for i in ids])
    M.append([Fraction(1) for _ in ids]);rhs=[Fraction(0),Fraction(0),Fraction(0),Fraction(1)]
    y=solve_unique_fraction(M,rhs)
    if y is None or any(q<0 for q in y):return None
    margin=sum(Fraction.from_float(float(b[i]))*y[j] for j,i in enumerate(ids))
    if margin<=0:return None
    return {"support_indices":ids,"weights_exact":[f"{q.numerator}/{q.denominator}" for q in y],
            "margin_exact":f"{margin.numerator}/{margin.denominator}","margin_float_km":float(margin)}

def active_set_min_norm(system):
    A=np.asarray(system.A,float);b=np.asarray(system.b,float)
    candidates=[]
    p0=np.zeros(3)
    if min_residual(system,p0)>=-WITNESS_RESID_KM:
        candidates.append(p0)
    for k in range(1,min(3,len(b))+1):
        for ids in combinations(range(len(b)),k):
            AI=A[list(ids)]; bi=b[list(ids)]
            G=AI@AI.T
            try:
                lam=np.linalg.solve(G,bi)
            except np.linalg.LinAlgError:
                continue
            if np.min(lam)<-1e-8:
                continue
            p=AI.T@lam
            if min_residual(system,p)>=-WITNESS_RESID_KM:
                candidates.append(p)
    if not candidates:
        return None
    return min(candidates,key=lambda p:float(np.linalg.norm(p)))

def _exact_vec3(v):
    return [Fraction.from_float(float(x)) for x in np.asarray(v,float)]

def exact_homogeneous_contains_fraction(A,d):
    if all(x==0 for x in d):return False
    for row in np.asarray(A,float):
        rf=[Fraction.from_float(float(x)) for x in row]
        if sum(rf[j]*d[j] for j in range(3)) < 0:return False
    return True

def _cross_fraction(a,b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

def exact_unbounded_direction(system):
    """Return an exact rational nonzero d with A d >= 0 when one is constructively found."""
    A=np.asarray(system.A,float)
    rows=[_exact_vec3(r) for r in A]
    axes=[[Fraction(1),0,0],[0,Fraction(1),0],[0,0,Fraction(1)]]
    candidates=[]
    # Axis directions cover unconstrained/halfspace-like recession cones.
    for e in axes:
        candidates.extend([e,[-x for x in e]])
    # Extreme rays of a rational 3-D polyhedral cone occur on intersections of facet planes;
    # row-axis crosses also cover simple lineality/one-plane cases.
    for a in rows:
        for e in axes:
            c=_cross_fraction(a,e)
            candidates.extend([c,[-x for x in c]])
    for i in range(len(rows)):
        for j in range(i+1,len(rows)):
            c=_cross_fraction(rows[i],rows[j])
            candidates.extend([c,[-x for x in c]])
    seen=set()
    for d in candidates:
        if all(x==0 for x in d):continue
        # Canonical scale by first nonzero coordinate for deduplication.
        first=next(x for x in d if x!=0)
        q=tuple(x/abs(first) for x in d)
        if q in seen:continue
        seen.add(q)
        if exact_homogeneous_contains_fraction(A,d):
            return d
    return None

def exact_conic_representation(rows,target):
    """Exact nonnegative representation target=sum(lambda_i*row_i), support <=3 (Caratheodory in R^3)."""
    rf=[_exact_vec3(r) for r in np.asarray(rows,float)]
    target=[Fraction(x) for x in target]
    for k in range(1,min(3,len(rf))+1):
        for ids in combinations(range(len(rf)),k):
            M=[[rf[i][dim] for i in ids] for dim in range(3)]
            y=solve_unique_fraction(M,target)
            if y is None or any(v<0 for v in y):continue
            replay=[sum(y[j]*rf[i][dim] for j,i in enumerate(ids)) for dim in range(3)]
            if replay==target:
                return {"support_indices":list(ids),"weights_exact":[f"{v.numerator}/{v.denominator}" for v in y]}
    return None

def exact_boundedness_certificate(system):
    """Prove recession cone {d:A d>=0} is {0} by proving +/-e_j are in cone(rows(A))."""
    cert={}
    axes=[(1,0,0),(0,1,0),(0,0,1)]
    for j,e in enumerate(axes):
        for sign in (1,-1):
            target=tuple(sign*x for x in e)
            rep=exact_conic_representation(system.A,target)
            if rep is None:return None
            cert[f"axis_{j}_{'pos' if sign>0 else 'neg'}"]=rep
    return cert

def recession_classify(system):
    """Return VERIFIED_UNBOUNDED, VERIFIED_BOUNDED, or UNRESOLVED with an exact proof object."""
    d=exact_unbounded_direction(system)
    if d is not None:
        return "VERIFIED_UNBOUNDED", np.asarray([float(x) for x in d],float), {
            "direction_exact":[f"{x.numerator}/{x.denominator}" for x in d]
        }
    bc=exact_boundedness_certificate(system)
    if bc is not None:
        return "VERIFIED_BOUNDED",None,bc
    return "UNRESOLVED",None,None

def recession_unbounded(system):
    """Compatibility wrapper for legacy fixtures; production code uses recession_classify()."""
    st,d,_=recession_classify(system)
    return st=="VERIFIED_UNBOUNDED",d

def exact_point_satisfies(system,pfrac):
    for row,b in zip(np.asarray(system.A,float),np.asarray(system.b,float)):
        rf=[Fraction.from_float(float(x)) for x in row]
        if sum(rf[j]*pfrac[j] for j in range(3)) < Fraction.from_float(float(b)):
            return False
    return True

def exact_bounded_vertices(system):
    """Exhaustively enumerate exact rational vertices from every independent 3-facet intersection."""
    A=np.asarray(system.A,float);b=np.asarray(system.b,float);verts=[];seen=set()
    for ids in combinations(range(len(b)),3):
        M=[_exact_vec3(A[i]) for i in ids]
        rhs=[Fraction.from_float(float(b[i])) for i in ids]
        p=solve_unique_fraction(M,rhs)
        if p is None or not exact_point_satisfies(system,p):continue
        key=tuple(p)
        if key not in seen:
            seen.add(key);verts.append((ids,p))
    return verts

def verified_bounded_max_vertex(system):
    verts=exact_bounded_vertices(system)
    if not verts:return None
    def n2(item):return sum(x*x for x in item[1])
    ids,p=max(verts,key=n2)
    return {"active_indices":list(ids),"point_exact":p,"distance2_exact":n2((ids,p))}

def max_norm_bounded(system):
    """Compatibility helper: only returns a maximum after an exact boundedness proof and exhaustive exact vertices."""
    st,_,_=recession_classify(system)
    if st!="VERIFIED_BOUNDED":return None
    q=verified_bounded_max_vertex(system)
    if q is None:return None
    return np.asarray([float(x) for x in q["point_exact"]],float)

def to_earth_fixed(site,v):
    """Rotate a celestial-frame vector into the terrestrial frame used by frozen site_celestial()."""
    v=np.asarray(v,float)
    if site is None:
        return v
    if not isinstance(site,dict) or "rc2t" not in site:
        raise ValueError("missing rc2t in site state")
    R=np.asarray(site["rc2t"],float)
    if R.shape!=(3,3) or not np.all(np.isfinite(R)):
        raise ValueError("invalid rc2t in site state")
    return R@v

def ellipsoid_value(p,site=None):
    q=to_earth_fixed(site,p) if site is not None else np.asarray(p,float)
    x,y,z=np.asarray(q,float)
    return (x*x+y*y)/(WGS84_A_KM**2)+(z*z)/(WGS84_B_KM**2)

def exact_ellipsoid_exterior(p,site=None):
    """Exact comparison to the WGS84 surface using the actual binary64 transformed coordinates/constants."""
    q=to_earth_fixed(site,p) if site is not None else np.asarray(p,float)
    x,y,z=(_F(v) for v in np.asarray(q,float))
    a=_F(WGS84_A_KM); b=_F(WGS84_B_KM)
    val=x*x/(a*a)+y*y/(a*a)+z*z/(b*b)
    return val >= 1

def exact_horizon_nonnegative(p,site):
    p=np.asarray(p,float); r=np.asarray(site["r"],float); up=unit(site["up"])
    d=p-r
    return exact_dot3(up,d) >= 0

def exact_segment_occulted(r,p,site=None):
    """Exact rational test, relative to binary64 transformed coordinates, for strict WGS84 interior crossing."""
    if site is not None:
        r=to_earth_fixed(site,r); p=to_earth_fixed(site,p)
    r=np.asarray(r,float); p=np.asarray(p,float)
    d=p-r
    if np.linalg.norm(d)<=RAY_ZERO_KM:
        return True
    rf=[_F(v) for v in r]; df=[_F(v) for v in d]
    a=_F(WGS84_A_KM); b=_F(WGS84_B_KM)
    inv=[1/(a*a),1/(a*a),1/(b*b)]
    qa=sum(df[j]*df[j]*inv[j] for j in range(3))
    qb=2*sum(rf[j]*df[j]*inv[j] for j in range(3))
    qc=sum(rf[j]*rf[j]*inv[j] for j in range(3))-1
    if qa<=0:
        return True
    lm=-qb/(2*qa)
    if lm<0: lm=Fraction(0)
    elif lm>1: lm=Fraction(1)
    qmin=qa*lm*lm+qb*lm+qc
    return qmin < 0

def segment_occulted(r,p,site=None):
    """Float diagnostic retained for fixtures; production witness verification uses exact_segment_occulted()."""
    if site is not None:
        r=to_earth_fixed(site,r); p=to_earth_fixed(site,p)
    else:
        r=np.asarray(r,float); p=np.asarray(p,float)
    r=np.asarray(r,float); p=np.asarray(p,float); d=p-r
    if np.linalg.norm(d)<=RAY_ZERO_KM:
        return True
    S=np.diag([1/WGS84_A_KM**2,1/WGS84_A_KM**2,1/WGS84_B_KM**2])
    qa=float(d@S@d); qb=2*float(r@S@d); qc=float(r@S@r)-1
    if qa<=0:return True
    lm=max(0.0,min(1.0,-qb/(2*qa)))
    qmin=qa*lm*lm+qb*lm+qc
    return qmin < -1e-11

def verify_physical_witness(p,siteA,siteB):
    """Conservative exact-sign verification under the frozen binary64 nominal geometry."""
    p=np.asarray(p,float)
    for site in (siteA,siteB):
        r=np.asarray(site["r"],float)
        if np.linalg.norm(p-r)<=RAY_ZERO_KM:
            return False,"ZERO_LENGTH_OBSERVER_RAY"
        if not exact_horizon_nonnegative(p,site):
            return False,"BELOW_HORIZON_OR_NUMERIC_BOUNDARY"
        if not exact_ellipsoid_exterior(p,site):
            return False,"INSIDE_WGS84_OR_NUMERIC_BOUNDARY"
        if exact_segment_occulted(r,p,site):
            return False,"EARTH_OCCULTED"
    return True,"PASS"

def fixed_time_component(system,siteA,siteB):
    feas,p,_=feasible_lp(system)
    if feas=="LP_INFEASIBLE":
        cert=exact_farkas_certificate(system)
        if cert:
            return FixedTimeResult("CERTIFIED_NONADMISSIBLE",None,None,None,False,None,None,cert,
                                   "Exact Farkas certificate relative to binary64 coefficients.")
        return FixedTimeResult("NUMERICALLY_UNRESOLVED",None,None,None,None,None,None,None,
                               "LP reported infeasible but exact certificate was not constructed.")
    if feas!="FEASIBLE":
        return FixedTimeResult("NUMERICALLY_UNRESOLVED",None,None,None,None,None,None,None,
                               "LP did not provide a verified witness.")

    pmin=active_set_min_norm(system)
    candidates=[]
    if pmin is not None:candidates.append(("min_norm",pmin))
    if p is not None:candidates.append(("lp",np.asarray(p,float)))
    verified=None
    for label,cand in candidates:
        if not exact_halfspace_contains(system,cand):continue
        ok,why=verify_physical_witness(cand,siteA,siteB)
        if ok:
            verified=(label,np.asarray(cand,float));break
    if verified is None:
        return FixedTimeResult("NUMERICALLY_UNRESOLVED",None,None,None,None,None,None,None,
                               "LP indicated feasibility but no exact-sign verified physical witness was obtained.")
    _,witness=verified

    # Lower extent remains optional: existence is never downgraded if the endpoint cannot be certified.
    dmin=None;lower_closed=None
    if pmin is not None and exact_halfspace_contains(system,pmin):
        okmin,_=verify_physical_witness(pmin,siteA,siteB)
        if okmin:
            dmin=float(np.linalg.norm(pmin));lower_closed=True

    rstate,rdir,rproof=recession_classify(system)
    if rstate=="VERIFIED_UNBOUNDED":
        return FixedTimeResult("ADMISSIBLE_WITNESS",witness,dmin,None,True,lower_closed,False,None,
                               "Existence verified; exact recession proof establishes arbitrarily large finite distances.")
    if rstate=="UNRESOLVED":
        return FixedTimeResult("ADMISSIBLE_WITNESS",witness,dmin,None,None,lower_closed,None,None,
                               "Existence verified; boundedness/unboundedness of the fixed-time component is unresolved.")

    # Only VERIFIED_BOUNDED reaches a finite maximum. Exhaustive exact rational vertex enumeration is the proof.
    vmax=verified_bounded_max_vertex(system)
    if vmax is None:
        return FixedTimeResult("ADMISSIBLE_WITNESS",witness,dmin,None,False,lower_closed,None,None,
                               "Existence and boundedness verified; finite maximum vertex enumeration unresolved.")
    pmax=np.asarray([float(x) for x in vmax["point_exact"]],float)
    if not exact_halfspace_contains(system,pmax):
        return FixedTimeResult("ADMISSIBLE_WITNESS",witness,dmin,None,False,lower_closed,None,None,
                               "Boundedness verified; rounded maximum endpoint failed exact binary64 halfspace replay.")
    ok2,why2=verify_physical_witness(pmax,siteA,siteB)
    if not ok2:
        return FixedTimeResult("ADMISSIBLE_WITNESS",witness,dmin,None,False,lower_closed,None,None,
                               f"Boundedness verified; maximum physical endpoint unresolved: {why2}")
    dmax=math.sqrt(float(vmax["distance2_exact"]))
    return FixedTimeResult("ADMISSIBLE_WITNESS",witness,dmin,dmax,False,lower_closed,True,None,
                           "Finite upper extent reported only after exact boundedness proof and exhaustive exact vertex maximization.")

def relaxed_footprint_system(edgeA,edgeB,rA0,rB0,rhoA,rhoB):
    """Whole-time-cell OUTER relaxation. Intentionally omits horizon and Earth constraints."""
    A=[];b=[];labels=[]
    for i,e in enumerate(edgeA):
        e=unit(e); A.append(e); b.append(float(e@rA0)-float(rhoA)); labels.append(f"A:relaxed_edge:{i}")
    for i,e in enumerate(edgeB):
        e=unit(e); A.append(e); b.append(float(e@rB0)-float(rhoB)); labels.append(f"B:relaxed_edge:{i}")
    return HalfspaceSystem(np.asarray(A),np.asarray(b),labels)

def whole_cell_exclusion(edgeA,edgeB,rA0,rB0,half_duration_s,crosses_reference_switch=False):
    rho=MOTION_BOUND_KM_S*float(half_duration_s)
    if crosses_reference_switch:
        rho+=REFERENCE_SWITCH_ALLOWANCE_KM
    sys=relaxed_footprint_system(edgeA,edgeB,rA0,rB0,rho,rho)
    # Horizon/Earth deliberately absent. Empty outer relaxation => safe exclusion under nominal model.
    state,_,_=feasible_lp(sys)
    if state=="LP_INFEASIBLE":
        cert=exact_farkas_certificate(sys)
        if cert:
            return "CELL_CERTIFIED_EMPTY",cert
    return "CELL_UNRESOLVED",None

def site_equator(lon_deg=0.0,h_km=0.0):
    l=math.radians(lon_deg)
    r=np.array([(WGS84_A_KM+h_km)*math.cos(l),(WGS84_A_KM+h_km)*math.sin(l),0.])
    up=unit(np.array([math.cos(l),math.sin(l),0.]))
    return {"r":r,"up":up,"rc2t":np.eye(3),"height_km":h_km}

def hs(rows,bs,labels=None):
    if labels is None:labels=[f"h{i}" for i in range(len(bs))]
    return HalfspaceSystem(np.asarray(rows,float),np.asarray(bs,float),labels)

def fixture_tests():
    out=[]

    # 1 bounded norm interval: 1<=x<=2, -1<=y,z<=1
    box=hs([[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]],
           [1,-2,-1,-1,-1,-1])
    dummyA={"r":np.array([10000.,10000.,10000.]),"up":unit([1,1,1]),"height_km":1}
    # Physical checks are not meaningful for arbitrary box, so test algebra directly.
    pmin=active_set_min_norm(box); ub,_=recession_unbounded(box); pmax=max_norm_bounded(box)
    assert abs(np.linalg.norm(pmin)-1)<1e-8 and not ub and abs(np.linalg.norm(pmax)-math.sqrt(6))<1e-7
    out.append("bounded_norm_interval PASS")

    # 2 unbounded component
    unb=hs([[1,0,0]],[1])
    pmin=active_set_min_norm(unb); ub,_=recession_unbounded(unb)
    assert abs(np.linalg.norm(pmin)-1)<1e-8 and ub
    out.append("unbounded_component PASS")

    # 3 finite-infeasible yet common recession direction z exists ("infinity-compatible")
    infonly=hs([[1,0,0],[-1,0,0]],[1,0],["x>=1","x<=0"])
    state,_,_=feasible_lp(infonly); cert=exact_farkas_certificate(infonly)
    ub,d=recession_unbounded(infonly)
    # recession of combined inequalities has nonzero y/z direction even though affine set is empty
    assert state=="LP_INFEASIBLE" and cert is not None and ub
    out.append("infinity_direction_compatible_but_finite_infeasible PASS")

    # 4 very distant finite bounded component
    D=1.0e9
    far=hs([[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]],
           [-1,1,-1,1,D,-(D+2)])
    state,p,_=feasible_lp(far); pmin=active_set_min_norm(far); pmax=max_norm_bounded(far)
    assert state=="FEASIBLE" and np.linalg.norm(pmin)>=D-1e-3 and np.linalg.norm(pmax)<=D+3
    out.append("very_distant_finite_intersection PASS")

    # 5 exact rational Farkas certificate replay
    c=exact_farkas_certificate(infonly)
    assert c and c["margin_float_km"]>0
    out.append("exact_farkas_certificate PASS")

    # 6 brief interior-time feasibility: x>=t^2, x<=0.25
    def brief(t):
        return hs([[1,0,0],[-1,0,0]],[t*t,-0.25])
    assert feasible_lp(brief(-1))[0]=="LP_INFEASIBLE"
    assert feasible_lp(brief(1))[0]=="LP_INFEASIBLE"
    assert feasible_lp(brief(0))[0]=="FEASIBLE"
    out.append("brief_interior_time_feasibility PASS")

    # 7 rotating-horizon safety: the cell relaxation must not contain any horizon label.
    edgesA=[np.array([1.,0,0])]; edgesB=[np.array([-1.,0,0])]
    rel=relaxed_footprint_system(edgesA,edgesB,np.array([0.,0,0]),np.array([0.,0,0]),1,1)
    assert all("horizon" not in x for x in rel.labels)
    out.append("rotating_horizon_omitted_from_cell_exclusion PASS")

    # 8 RA-wrap polygon around 0 degrees.
    poly=[xyz(359,-1),xyz(1,-1),xyz(1,1),xyz(359,1)]
    tris=triangulate_spherical_polygon(poly)
    assert len(tris)==2
    for tri in tris:convex_component_edge_normals(tri)
    out.append("ra_wrap_polygon PASS")

    # 9 concave quadrilateral decomposition.
    conc=[xyz(0,0),xyz(2,0),xyz(0.7,0.4),xyz(0,2)]
    tris=triangulate_spherical_polygon(conc)
    assert len(tris)==2
    for tri in tris:convex_component_edge_normals(tri)
    out.append("concave_polygon_decomposition PASS")

    # 10 WGS84 horizon implies exterior for an exact witness; independent segment check.
    st=site_equator(0,1.0); p=st["r"]+100*st["up"]
    assert ellipsoid_value(p,st)>1 and not segment_occulted(st["r"],p,st)
    assert float(st["up"]@(p-st["r"]))>0
    out.append("wgs84_horizon_exterior_occultation PASS")

    # 11 Rotated WGS84 frame: celestial P must be transformed with the same rc2t as the site state.
    th=math.radians(37.0)
    R=np.array([[math.cos(th),0,math.sin(th)],[0,1,0],[-math.sin(th),0,math.cos(th)]])
    q=np.array([0.,0.,WGS84_B_KM+10.])                 # terrestrial point just above north pole
    r_ef=np.array([0.,0.,WGS84_B_KM+1.])
    p_c=R.T@q; r_c=R.T@r_ef; up_c=unit(R.T@np.array([0.,0.,1.]))
    sr={"r":r_c,"up":up_c,"rc2t":R,"height_km":1.0}
    assert ellipsoid_value(p_c,sr)>1
    assert not segment_occulted(r_c,p_c,sr)
    assert verify_physical_witness(p_c,sr,sr)[0]
    out.append("rotated_wgs84_frame PASS")

    # Parent-integration guard: Earth-frame checks must never silently skip the inherited rc2t transform.
    missing={"r":r_c,"up":up_c,"height_km":1.0}
    try:
        ellipsoid_value(p_c,missing)
        raise AssertionError("missing rc2t was silently accepted")
    except ValueError as exc:
        assert "rc2t" in str(exc)
    out.append("missing_rc2t_rejected PASS")

    # 12 A<->B symmetry of combined halfspaces.
    a=hs([[1,0,0]],[1],["A"]); b=hs([[0,1,0]],[2],["B"])
    ab=combine(a,b); ba=combine(b,a)
    pa=active_set_min_norm(ab); pb=active_set_min_norm(ba)
    assert abs(np.linalg.norm(pa)-np.linalg.norm(pb))<1e-10
    out.append("A_B_symmetry PASS")

    # 13 Whole-cell certified empty with explicit outer relaxation.
    # x >= 10-rho and x <= 0+rho; halfwidth 1s => rho=.6, still impossible.
    state,cert=whole_cell_exclusion([np.array([1.,0,0])],[np.array([-1.,0,0])],
                                    np.array([10.,0,0]),np.array([0.,0,0]),1.0)
    assert state=="CELL_CERTIFIED_EMPTY" and cert is not None
    out.append("whole_time_cell_outer_relaxation_certificate PASS")

    # 14 Tolerance-only near-boundary points must not become production positives.
    near=hs([[1,0,0]],[1.0],["x>=1"])
    p_bad=np.array([1.0-1e-12,0.,0.])
    assert min_residual(near,p_bad)>-WITNESS_RESID_KM
    assert not exact_halfspace_contains(near,p_bad)
    p_good=np.array([1.0,0.,0.])
    assert exact_halfspace_contains(near,p_good)
    out.append("exact_positive_halfspace_sign_gate PASS")

    # 15 Explicit three-state recession proof: bounded box.
    rs,rd,rp=recession_classify(box)
    assert rs=="VERIFIED_BOUNDED" and rd is None and isinstance(rp,dict)
    out.append("verified_bounded_recession_certificate PASS")

    # 16 Narrow non-axis exact ray must be proved unbounded rather than misreported finite.
    ray=hs([[-2,1,0],[2,-1,0],[-3,0,1],[3,0,-1],[1,0,0]], [0,0,0,0,0])
    rs,rd,rp=recession_classify(ray)
    assert rs=="VERIFIED_UNBOUNDED" and rd is not None and exact_homogeneous_contains(ray.A,rd)
    out.append("verified_narrow_recession_ray PASS")

    # 17 Exhaustive exact bounded maximum must dominate every verified feasible vertex.
    vmax=verified_bounded_max_vertex(box)
    assert vmax is not None and abs(math.sqrt(float(vmax["distance2_exact"]))-math.sqrt(6))<1e-12
    out.append("verified_bounded_maximum PASS")

    # 18 Self-crossing original footprint must be rejected before triangulation.
    crossed=[xyz(0,0),xyz(3,3),xyz(0,2),xyz(2,0)]
    rejected=False
    try:triangulate_spherical_polygon(crossed)
    except ValueError:rejected=True
    assert rejected
    out.append("self_crossing_polygon_rejected PASS")
    return out

def load_module(path,name):
    sp=importlib.util.spec_from_file_location(name,path)
    if sp is None or sp.loader is None:raise RuntimeError(f"cannot load {path}")
    m=importlib.util.module_from_spec(sp);sys.modules[name]=m;sp.loader.exec_module(m);return m

def integration_smoke(project_root,repo_root):
    """Read-only structural smoke test on declared real parent inputs; NOT a production search."""
    project=Path(project_root); repo=Path(repo_root)
    v094x_path=project/"tools"/"run_v094x_source_free_full_population_finite_geometry_synthetic_validation.py"
    if not v094x_path.is_file() or sha(v094x_path)!=FROZEN_V094X_SHA:
        raise SystemExit("INTEGRATION_HOLD: frozen v094x runner SHA mismatch")
    vx=load_module(v094x_path,"v094x_parent_for_v094y_prototype")
    geom=vx.load_parent_geometry(repo)
    sites,refs,polys,overlap=vx.load_foundation(repo,geom)
    if len(overlap)!=8807:
        raise SystemExit(f"INTEGRATION_HOLD: overlap count {len(overlap)}")
    # Structural-only declared indices: first, middle, monthly-era representative, last.
    indices=[1,4404,6983,8807]
    report=[]
    for idx in indices:
        row=overlap[idx-1]
        intervals=vx.parse_intervals(row)
        if not intervals:raise SystemExit(f"INTEGRATION_HOLD: no intervals at {idx}")
        t=intervals[0][0]+(intervals[0][1]-intervals[0][0])/2
        siteA=sites[str(row["site_a"]).strip()];siteB=sites[str(row["site_b"]).strip()]
        g=geom.geometry_at(siteA,siteB,t,refs)
        if g is None:raise SystemExit(f"INTEGRATION_HOLD: geometry missing at {idx}")
        Astate,Bstate,_=g
        polyA=[xyz(*q) for q in polys[vx.inum(row["solution_id_a"])]]
        polyB=[xyz(*q) for q in polys[vx.inum(row["solution_id_b"])]]
        compA=triangulate_spherical_polygon(polyA)
        compB=triangulate_spherical_polygon(polyB)
        # Validate fixed-time component construction; do not classify the pair globally.
        combo_states=[]
        for ia,ta in enumerate(compA):
            ea=convex_component_edge_normals(ta)
            sa=component_halfspaces(ea,Astate["r"],"A")
            sa=add_horizon(sa,Astate["r"],Astate["up"],"A")
            for ib,tb in enumerate(compB):
                eb=convex_component_edge_normals(tb)
                sb=component_halfspaces(eb,Bstate["r"],"B")
                sb=add_horizon(sb,Bstate["r"],Bstate["up"],"B")
                sys=combine(sa,sb)
                state,p,_=feasible_lp(sys)
                if state=="LP_INFEASIBLE":
                    cert=exact_farkas_certificate(sys)
                    combo_states.append("CERT" if cert else "UNRESOLVED")
                else:
                    combo_states.append(state)
        report.append({
            "pair_index":idx,"pair_id":row.get("pair_id"),
            "components_A":len(compA),"components_B":len(compB),
            "fixed_time_component_screen_states":combo_states
        })
    return {
        "status":"INTEGRATION_SMOKE_PASS",
        "production_pairs_processed":0,
        "population_replayed":len(overlap),
        "declared_structural_samples":report,
        "note":"No pair-level production admissibility status is emitted by this smoke test."
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--integration-smoke",action="store_true")
    ap.add_argument("--project-root")
    ap.add_argument("--repo-root")
    a=ap.parse_args()
    if a.self_test:
        results=fixture_tests()
        print("="*96)
        print("v094y RC4 FINITE-GEOMETRY CORE SELF-TEST")
        print("="*96)
        for x in results:print(x)
        print(f"Fixtures: {len(results)}/{len(results)} PASS")
        print("CORE SELF-TEST ONLY: no production population processed.")
        return 0
    if a.integration_smoke:
        if not a.project_root or not a.repo_root:
            raise SystemExit("--project-root and --repo-root required")
        print(json.dumps(integration_smoke(a.project_root,a.repo_root),indent=2))
        return 0
    ap.print_help()
    return 0

if __name__=="__main__":
    raise SystemExit(main())
