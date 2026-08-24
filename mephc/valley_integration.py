"""Production retained-domain plans and fail-closed Berry-row reduction.

This module is solver-neutral: it consumes supplied Berry samples and never
invokes an eigensolver or computes Berry curvature.
"""
from __future__ import annotations
import hashlib, json, math
from dataclasses import dataclass

SOURCE_GRID_MIDPOINT_V1 = "SOURCE_GRID_MIDPOINT_V1"
MEPHC_CLIPPED_RETAINED_DOMAIN_V1 = "MEPHC_CLIPPED_RETAINED_DOMAIN_V1"
SOURCE_H = 1.0 / 36.0
EPS = 1e-12

class IntegrationPlanError(ValueError): pass

def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
def _area(poly): return 0.5 * sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[i][1]*poly[(i+1)%len(poly)][0] for i in range(len(poly)))
def _ccw(poly): return list(poly) if _area(poly)>0 else list(reversed(poly))
def _cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
def _point_in(poly,p): return all(_cross(a,b,p)>=-EPS for a,b in zip(_ccw(poly),_ccw(poly)[1:]+_ccw(poly)[:1]))
def _clip(poly,a,b,inside=True):
    if not poly: return []
    out=[]
    for p,q in zip(poly,poly[1:]+poly[:1]):
        vp,vq=_cross(a,b,p),_cross(a,b,q); pin=vp>=-EPS if inside else vp<=EPS; qin=vq>=-EPS if inside else vq<=EPS
        if pin: out.append(p)
        if pin!=qin and abs(vp-vq)>EPS:
            t=vp/(vp-vq); out.append((p[0]+t*(q[0]-p[0]),p[1]+t*(q[1]-p[1])))
    return out
def _intersection(*polys):
    out=list(polys[0])
    for poly in polys[1:]:
        for a,b in zip(_ccw(poly),_ccw(poly)[1:]+_ccw(poly)[:1]):
            out=_clip(out,a,b,True)
            if len(out)<3:return []
    return out
def _intersection_area(*polys):
    p=_intersection(*polys); return abs(_area(p)) if len(p)>=3 else 0.0
def _square(q,side):
    h=side/2; return [(q[0]-h,q[1]-h),(q[0]+h,q[1]-h),(q[0]+h,q[1]+h),(q[0]-h,q[1]+h)]
def _regular(center,radius,sides,rotation=0.0):
    return [(center[0]+radius*math.cos(rotation+2*math.pi*i/sides),center[1]+radius*math.sin(rotation+2*math.pi*i/sides)) for i in range(sides)]
def _neg(poly): return [(-x,-y) for x,y in poly]
def _scale(poly,center,factor): return [(center[0]+factor*(x-center[0]),center[1]+factor*(y-center[1])) for x,y in poly]
def _subtract(poly,hole):
    active=[list(poly)]; result=[]
    for a,b in zip(_ccw(hole),_ccw(hole)[1:]+_ccw(hole)[:1]):
        nxt=[]
        for piece in active:
            inn=_clip(piece,a,b,True); out=_clip(piece,a,b,False)
            if len(out)>=3 and abs(_area(out))>EPS: result.append(out)
            if len(inn)>=3 and abs(_area(inn))>EPS: nxt.append(inn)
        active=nxt
    return result
def _triangles(poly):
    poly=_ccw(poly); out=[]
    for i in range(1,len(poly)-1):
        tri=[poly[0],poly[i],poly[i+1]]; weight=abs(_area(tri))
        if weight>EPS: out.append((tri,weight))
    return out

@dataclass(frozen=True)
class RetainedDomain:
    case: str
    outer: tuple[tuple[float,float],...]
    exclusions: tuple[tuple[tuple[float,float],...],...]
    delta_k: float
    delta_gamma: float

    @property
    def digest(self):
        return _digest(self.to_dict())
    @property
    def area_q2(self):
        return abs(_area(self.outer))-sum(_intersection_area(self.outer,h) for h in self.exclusions)
    def to_dict(self): return {"case":self.case,"outer":[list(x) for x in self.outer],"exclusions":[[list(x) for x in h] for h in self.exclusions],"delta_K":self.delta_k,"delta_Gamma":self.delta_gamma}

def build_source_bound_domain(fr):
    if float(fr) not in (0.0,0.4): raise ValueError("supported cases are fr=0 and fr=0.4")
    dk,dg=(0.10,0.10) if float(fr)==0.0 else (0.05,0.13)
    k=(2.0/3.0,0.0); kp=(-2.0/3.0,0.0); radius=2.0/3.0
    k_triangle=_regular(k,radius,3,math.pi/3.0); kp_triangle=_neg(k_triangle)
    outer=_scale(kp_triangle,kp,(radius-dk)/radius)
    holes=tuple(tuple(tuple(x) for x in _regular(v,dg,6,0.0)) for v in kp_triangle)
    return RetainedDomain(f"fr={float(fr):g}",tuple(tuple(x) for x in outer),holes,dk,dg)

def _grid_nodes(domain):
    minx=min(x for x,_ in domain.outer)-SOURCE_H; maxx=max(x for x,_ in domain.outer)+SOURCE_H; miny=min(y for _,y in domain.outer)-SOURCE_H; maxy=max(y for _,y in domain.outer)+SOURCE_H
    for i in range(math.floor(minx*36)-1,math.ceil(maxx*36)+2):
        for j in range(math.floor(miny*36)-1,math.ceil(maxy*36)+2): yield i,j,(i/36,j/36)
def _retained(domain,q): return _point_in(domain.outer,q) and not any(_point_in(h,q) for h in domain.exclusions)
def _cell_fragments(domain,q):
    pieces=[_intersection(domain.outer,_square(q,SOURCE_H))]
    if not pieces[0] or len(pieces[0])<3:return []
    for hole in domain.exclusions:
        nxt=[]
        for piece in pieces:nxt.extend(_subtract(piece,hole))
        pieces=nxt
    return pieces
def _sample_id(domain,est,i,j,fragment=0,triangle=0):
    if est==SOURCE_GRID_MIDPOINT_V1:return f"{domain.case};grid_i={i};grid_j={j};estimator=SOURCE_GRID"
    return f"{domain.case};grid_i={i};grid_j={j};fragment_index={fragment};triangle_index={triangle};estimator=MEPHC_CLIPPED"
def _row(domain,est,sid,q,w,i,j,fragment=None,triangle=None):
    return {"ESTIMATOR_ID":est,"SAMPLE_ID":sid,"PUBLIC_Q":tuple(float(x) for x in q),"WEIGHT_Q2":float(w),"DOMAIN_ID_OR_DIGEST":domain.digest,"GRID_INDEX":(i,j),"FRAGMENT_INDEX":fragment,"TRIANGLE_INDEX":triangle,"PUBLIC_Q_HEX_FLOATS":tuple(float(x).hex() for x in q)}

def build_integration_plan(domain,estimator_id):
    if estimator_id not in (SOURCE_GRID_MIDPOINT_V1,MEPHC_CLIPPED_RETAINED_DOMAIN_V1): raise IntegrationPlanError("unknown estimator")
    rows=[]
    for i,j,q in _grid_nodes(domain):
        if estimator_id==SOURCE_GRID_MIDPOINT_V1:
            if _retained(domain,q): rows.append(_row(domain,estimator_id,_sample_id(domain,estimator_id,i,j),q,SOURCE_H**2,i,j))
            continue
        cell=_square(q,SOURCE_H); outer_area=_intersection_area(domain.outer,cell); hole_area=sum(_intersection_area(domain.outer,h,cell) for h in domain.exclusions); weight=max(0.0,outer_area-hole_area)
        if weight<=EPS: continue
        full=abs(weight-SOURCE_H**2)<=1e-12 and _retained(domain,q) and all(_point_in(domain.outer,p) for p in cell) and not any(_intersection_area(domain.outer,h,cell)>EPS for h in domain.exclusions)
        if full:
            rows.append(_row(domain,estimator_id,_sample_id(domain,estimator_id,i,j),q,weight,i,j,0,0)); continue
        index=0
        for fi,piece in enumerate(_cell_fragments(domain,q)):
            for ti,(tri,w) in enumerate(_triangles(piece)):
                sample=tuple(sum(p[d] for p in tri)/3.0 for d in (0,1)); rows.append(_row(domain,estimator_id,_sample_id(domain,estimator_id,i,j,index,index),sample,w,i,j,index,index)); index+=1
    plan={"ESTIMATOR_ID":estimator_id,"DOMAIN_DIGEST":domain.digest,"ROWS":tuple(rows),"SAMPLE_COUNT":len(rows),"TOTAL_WEIGHT_Q2":sum(r["WEIGHT_Q2"] for r in rows)}
    validate_integration_plan(plan); plan["PLAN_DIGEST"]=_digest(_canonical_plan(plan)); return plan

def _canonical_plan(plan): return [{k:plan["ROWS"][i][k] for k in ("ESTIMATOR_ID","SAMPLE_ID","PUBLIC_Q_HEX_FLOATS","WEIGHT_Q2","DOMAIN_ID_OR_DIGEST","GRID_INDEX","FRAGMENT_INDEX","TRIANGLE_INDEX")} for i in sorted(range(len(plan["ROWS"])),key=lambda n:plan["ROWS"][n]["SAMPLE_ID"])]
def validate_integration_plan(plan):
    est=plan.get("ESTIMATOR_ID"); rows=plan.get("ROWS")
    if est not in (SOURCE_GRID_MIDPOINT_V1,MEPHC_CLIPPED_RETAINED_DOMAIN_V1) or not isinstance(rows,(tuple,list)): raise IntegrationPlanError("invalid plan")
    ids=set()
    for r in rows:
        if r.get("ESTIMATOR_ID")!=est or r.get("SAMPLE_ID") in ids: raise IntegrationPlanError("mixed or duplicate estimator/sample")
        ids.add(r.get("SAMPLE_ID")); q=r.get("PUBLIC_Q"); w=r.get("WEIGHT_Q2")
        if not isinstance(q,(tuple,list)) or len(q)!=2 or not all(math.isfinite(float(x)) for x in q): raise IntegrationPlanError("finite public q required")
        if not math.isfinite(float(w)) or float(w)<=0: raise IntegrationPlanError("positive weights required")
    return True

def reduce_supplied_berry_rows(plan, berry_rows, band_id):
    validate_integration_plan(plan); est=plan["ESTIMATOR_ID"]
    if any(r.get("ESTIMATOR_ID")!=est for r in berry_rows): raise IntegrationPlanError("MIXED_ESTIMATOR_PLAN_REJECTED")
    required={r["SAMPLE_ID"]:r for r in plan["ROWS"]}; grouped={}
    for row in berry_rows:
        sid=row.get("SAMPLE_ID")
        if sid not in required: raise IntegrationPlanError("unknown sample row")
        if row.get("BAND_ID")!=band_id: raise IntegrationPlanError("band mismatch")
        grouped.setdefault(sid,[]).append(row)
    missing=set(required)-set(grouped)
    if missing: raise IntegrationPlanError("MISSING_ROW")
    if any(len(v)!=1 for v in grouped.values()): raise IntegrationPlanError("DUPLICATE_ROW")
    statuses=[grouped[s][0] for s in required]
    for row in statuses:
        expected=required[row["SAMPLE_ID"]]
        if float(row.get("WEIGHT_Q2"))!=float(expected["WEIGHT_Q2"]): raise IntegrationPlanError("FAILED_WEIGHT_REMOVAL_OR_RENORMALIZATION")
        if row.get("STATUS") not in ("QUALIFIED_REPORTED","NOT_REPORTED_WITH_REASON"): raise IntegrationPlanError("terminal status required")
        if row.get("STATUS")=="QUALIFIED_REPORTED":
            value=row.get("OMEGA_Q")
            if value is None or not math.isfinite(float(value)): raise IntegrationPlanError("NAN_OR_INF_REPORTED_VALUE")
        elif "OMEGA_Q" in row and row.get("OMEGA_Q") in (0,0.0): raise IntegrationPlanError("ZERO_FILL_FOR_FAILED_SAMPLE")
    not_reported=[r for r in statuses if r["STATUS"]=="NOT_REPORTED_WITH_REASON"]
    status_digest=_digest(sorted([{k:r.get(k) for k in ("SAMPLE_ID","BAND_ID","STATUS","REASON")} for r in statuses],key=lambda x:x["SAMPLE_ID"]))
    base={"ESTIMATOR_ID":est,"DOMAIN_DIGEST":plan["DOMAIN_DIGEST"],"PLAN_DIGEST":plan["PLAN_DIGEST"],"STATUS_DIGEST":status_digest,"BAND_ID":band_id,"SAMPLE_COUNT":len(statuses),"TOTAL_WEIGHT_Q2":plan["TOTAL_WEIGHT_Q2"],"QUALIFIED_SAMPLE_COUNT":len(statuses)-len(not_reported),"NOT_REPORTED_SAMPLE_COUNT":len(not_reported),"NORMALIZATION_ID":"PUBLIC_Q_OMEGA_OVER_2PI","COMPLETE_STATUS":"INCOMPLETE_NOT_REPORTED" if not_reported else "COMPLETE"}
    if not_reported: return {**base,"FLUX_Q":"NOT_EMITTED","VALLEY_CHERN":"NOT_EMITTED","FAILURE_PROVENANCE":{"status":"NOT_REPORTED_WITH_REASON","sample_ids":[r["SAMPLE_ID"] for r in not_reported]}}
    flux=sum(float(r["OMEGA_Q"])*float(r["WEIGHT_Q2"]) for r in statuses)
    return {**base,"FLUX_Q":flux,"VALLEY_CHERN":flux/(2*math.pi)}

def build_berry_row(plan_row,band_id,status,omega_q=None,reason=None):
    row={"ESTIMATOR_ID":plan_row["ESTIMATOR_ID"],"SAMPLE_ID":plan_row["SAMPLE_ID"],"BAND_ID":band_id,"STATUS":status,"WEIGHT_Q2":plan_row["WEIGHT_Q2"]}
    if omega_q is not None: row["OMEGA_Q"]=omega_q
    if reason is not None: row["REASON"]=reason
    return row
